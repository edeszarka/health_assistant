"""Recommendations router: personalised screening via ScreeningService."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import ScreeningRecommendation
from models.db_models import UserProfile, FamilyHistory, LabResult
from services.risk_score_service import compute_baseline_scores
from services.screening_service import screening_service

router = APIRouter()


@router.get("/", response_model=List[ScreeningRecommendation])
async def get_recommendations(db: AsyncSession = Depends(get_db)) -> list[ScreeningRecommendation]:
    """Return personalised screening recommendations.

    Args:
        db: Async DB session.
    """
    # User profile
    result = await db.execute(select(UserProfile).limit(1))
    profile = result.scalar_one_or_none()
    age = getattr(profile, "age", 40)
    sex = getattr(profile, "sex", "other")

    # Family history conditions
    result = await db.execute(select(FamilyHistory.condition))
    fam_conditions = [row[0] for row in result.fetchall()]

    # Flagged lab keys
    result = await db.execute(
        select(LabResult.test_name).where(LabResult.is_flagged.is_(True))
    )
    flagged_keys = list({row[0] for row in result.fetchall()})

    # Baseline risk scores — computed and persisted by the shared service
    risk_scores = await compute_baseline_scores(db, profile)
    framingham_pct = risk_scores.get("framingham_risk_percent")
    findrisc_pts = risk_scores.get("findrisc_score")

    return await screening_service.get_recommendations(
        age=age,
        sex=sex,
        family_history_conditions=fam_conditions,
        flagged_lab_keys=flagged_keys,
        framingham_score=framingham_pct,
        findrisc_score=findrisc_pts,
        db=db,
    )
