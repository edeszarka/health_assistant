"""Dashboard router: aggregated health summary."""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import DashboardSummary, LabResultResponse, BPSummaryResponse
from models.db_models import LabResult, RiskScore, UserProfile
from routers.blood_pressure import bp_summary
from services.risk_engine import risk_engine

router = APIRouter()

# How many of the most recently stored lab rows the summary lists.
LATEST_LABS_LIMIT = 10
# The risk scores the summary shows. Each blood pressure reading also writes a
# bp_classification row to the same table, so these are selected by type; the
# blood pressure has its own place on the dashboard.
DASHBOARD_SCORE_TYPES = ("framingham", "findrisc")


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


def visible_risk_scores(
    rows: Iterable[RiskScore], profile: Optional[UserProfile]
) -> list[dict[str, Any]]:
    """Return the newest saved score of each type that may still be shown.

    A saved Framingham score stays in the table when the profile changes, so it
    is hidden here once the table no longer applies (ARCHITECTURE.md, Invariant 8).

    Args:
        rows: Saved scores, newest first.
        profile: The single user profile, or ``None`` when none exists.

    Returns:
        One dict per score type, newest first.
    """
    framingham_withheld = risk_engine.framingham_unavailable_reason(
        getattr(profile, "sex", None),
        bool(getattr(profile, "diabetes_diagnosed", False)),
        getattr(profile, "age", None),
    )
    newest: dict[str, RiskScore] = {}
    for row in rows:
        if row.score_type not in DASHBOARD_SCORE_TYPES or row.score_type in newest:
            continue
        if row.score_type == "framingham" and framingham_withheld:
            continue
        newest[row.score_type] = row
    return [
        {
            "score_type": row.score_type,
            "score_value": row.score_value,
            "risk_category": row.risk_category,
        }
        for row in newest.values()
    ]


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

    stmt2 = select(RiskScore).order_by(RiskScore.calculated_at.desc())
    result2 = await db.execute(stmt2)
    profile_result = await db.execute(select(UserProfile).limit(1))
    risk_scores = visible_risk_scores(
        result2.scalars().all(), profile_result.scalar_one_or_none()
    )

    return DashboardSummary(
        latest_labs=latest_labs,
        bp_summary=bp,
        risk_scores=risk_scores,
        active_flags=active_flags,
    )
