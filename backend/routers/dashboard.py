"""Dashboard router: aggregated health summary."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import DashboardSummary, LabResultResponse, BPSummaryResponse
from models.db_models import LabResult, RiskScore
from routers.blood_pressure import bp_summary

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    """Return a consolidated health summary for the dashboard.

    Args:
        db: Async DB session.
    """
    # Latest 10 lab results
    stmt = (
        select(LabResult)
        .order_by(LabResult.created_at.desc())
        .limit(10)
    )
    result = await db.execute(stmt)
    latest_labs = [
        LabResultResponse.model_validate(r) for r in result.scalars().all()
    ]

    # Active flags
    flagged = [lab for lab in latest_labs if lab.is_flagged]
    active_flags = [f"{lab.test_name}: {lab.value} {lab.unit}" for lab in flagged]

    # BP summary (reuse existing endpoint logic)
    try:
        bp = await bp_summary(db)
    except Exception:
        bp = None

    # Latest risk scores
    stmt2 = select(RiskScore).order_by(RiskScore.calculated_at.desc()).limit(5)
    result2 = await db.execute(stmt2)
    risk_rows = result2.scalars().all()
    risk_scores = [
        {
            "score_type": r.score_type,
            "score_value": r.score_value,
            "risk_category": r.risk_category,
        }
        for r in risk_rows
    ]

    return DashboardSummary(
        latest_labs=latest_labs,
        bp_summary=bp,
        risk_scores=risk_scores,
        active_flags=active_flags,
        recommendations_count=0,  # filled by frontend from /recommendations
    )
