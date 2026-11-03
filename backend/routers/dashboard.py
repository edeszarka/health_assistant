"""Dashboard router: aggregated health summary."""
from __future__ import annotations

from datetime import date
from typing import Iterable

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import DashboardSummary, LabResultResponse, BPSummaryResponse
from models.db_models import LabResult, RiskScore
from routers.blood_pressure import bp_summary

router = APIRouter()

# How many of the most recently stored lab rows the summary lists.
LATEST_LABS_LIMIT = 10


def latest_result_per_test(labs: Iterable[LabResult]) -> list[LabResult]:
    """Return each test's latest result, by test date and then by storage order.

    Args:
        labs: Lab rows in any order.

    Returns:
        One row per test, sorted by test name.
    """
    latest: dict[str, LabResult] = {}
    for lab in sorted(labs, key=lambda row: (row.test_date or date.min, row.id)):
        latest[lab.test_name] = lab
    return [latest[name] for name in sorted(latest)]


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    """Return a consolidated health summary for the dashboard.

    Args:
        db: Async DB session.
    """
    stmt = select(LabResult).order_by(LabResult.created_at.desc(), LabResult.id.desc())
    result = await db.execute(stmt)
    labs = result.scalars().all()
    latest_labs = [
        LabResultResponse.model_validate(r) for r in labs[:LATEST_LABS_LIMIT]
    ]

    # Active flags: every test whose latest result is flagged, wherever it was stored
    active_flags = [
        f"{lab.test_name}: {lab.value} {lab.unit or ''}".strip()
        for lab in latest_result_per_test(labs)
        if lab.is_flagged
    ]

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
    )
