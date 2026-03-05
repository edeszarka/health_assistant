"""Blood pressure router: CRUD + summary with AHA classification."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.connection import get_db
from backend.models.api_models import (
    BloodPressureCreate,
    BloodPressureResponse,
    BPSummaryResponse,
)
from backend.models.db_models import BloodPressureReading, RiskScore
from backend.services.risk_engine import risk_engine

router = APIRouter()


@router.get("/", response_model=List[BloodPressureResponse])
async def list_bp_readings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[BloodPressureReading]:
    """List all BP readings, paginated (newest first).

    Args:
        skip: Number of records to skip.
        limit: Max records to return.
        db: Async DB session.
    """
    stmt = (
        select(BloodPressureReading)
        .order_by(BloodPressureReading.measured_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    # Attach classification to each reading
    out = []
    for r in rows:
        cls = risk_engine.classify_blood_pressure(r.systolic, r.diastolic)
        out.append(
            BloodPressureResponse(
                id=r.id,
                measured_at=r.measured_at,
                systolic=r.systolic,
                diastolic=r.diastolic,
                pulse=r.pulse,
                context=r.context,
                classification=cls["category"],
                created_at=r.created_at,
            )
        )
    return out


@router.post("/", response_model=BloodPressureResponse, status_code=201)
async def create_bp_reading(
    data: BloodPressureCreate,
    db: AsyncSession = Depends(get_db),
) -> BloodPressureResponse:
    """Create a new BP reading, classify it, and persist a RiskScore row.

    Args:
        data: BloodPressureCreate payload.
        db: Async DB session.
    """
    measured_at = data.measured_at or datetime.now(timezone.utc)
    reading = BloodPressureReading(
        measured_at=measured_at,
        systolic=data.systolic,
        diastolic=data.diastolic,
        pulse=data.pulse,
        context=data.context,
    )
    db.add(reading)
    await db.flush()

    classification = risk_engine.classify_blood_pressure(data.systolic, data.diastolic)
    risk = RiskScore(
        score_type="bp_classification",
        score_value=float(data.systolic),
        risk_category=classification["category"],
        inputs_json=json.dumps(
            {"systolic": data.systolic, "diastolic": data.diastolic}
        ),
    )
    db.add(risk)
    await db.commit()
    await db.refresh(reading)

    return BloodPressureResponse(
        id=reading.id,
        measured_at=reading.measured_at,
        systolic=reading.systolic,
        diastolic=reading.diastolic,
        pulse=reading.pulse,
        context=reading.context,
        classification=classification["category"],
        created_at=reading.created_at,
    )


@router.get("/summary", response_model=BPSummaryResponse)
async def bp_summary(db: AsyncSession = Depends(get_db)) -> BPSummaryResponse:
    """Return 7-day and 30-day BP averages, trend, and AHA classification.

    Args:
        db: Async DB session.
    """
    now = datetime.now(timezone.utc)

    async def avg_over_days(days: int) -> tuple[Optional[float], Optional[float]]:
        since = now - timedelta(days=days)
        stmt = select(
            func.avg(BloodPressureReading.systolic),
            func.avg(BloodPressureReading.diastolic),
        ).where(BloodPressureReading.measured_at >= since)
        res = await db.execute(stmt)
        row = res.fetchone()
        return (float(row[0]) if row[0] else None, float(row[1]) if row[1] else None)

    sys7, dia7 = await avg_over_days(7)
    sys30, dia30 = await avg_over_days(30)

    # Classification based on 30-day average (falls back to 7-day, then defaults)
    sys_cls = sys30 or sys7 or 120
    dia_cls = dia30 or dia7 or 80
    cls = risk_engine.classify_blood_pressure(int(sys_cls), int(dia_cls))

    # Trend: compare 7-day vs 30-day systolic
    if sys7 and sys30:
        if sys7 < sys30 - 3:
            trend = "improving"
        elif sys7 > sys30 + 3:
            trend = "worsening"
        else:
            trend = "stable"
    else:
        trend = "stable"

    stmt = select(func.count(BloodPressureReading.id))
    res = await db.execute(stmt)
    count = res.scalar_one_or_none() or 0

    return BPSummaryResponse(
        avg_systolic_7d=round(sys7, 1) if sys7 else None,
        avg_diastolic_7d=round(dia7, 1) if dia7 else None,
        avg_systolic_30d=round(sys30, 1) if sys30 else None,
        avg_diastolic_30d=round(dia30, 1) if dia30 else None,
        classification=cls["category"],
        trend_direction=trend,
        reading_count=count,
    )
