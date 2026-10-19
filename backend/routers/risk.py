"""Risk router: read and save the risk-score inputs, then compute the scores."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import (
    RiskCalculationResponse,
    RiskInputsStatus,
    RiskInputsUpdate,
)
from services.risk_inputs import collect_inputs, load_profile, save_inputs
from services.risk_score_service import compute_baseline_scores

router = APIRouter()


@router.get("/inputs", response_model=RiskInputsStatus)
async def get_risk_inputs(db: AsyncSession = Depends(get_db)) -> RiskInputsStatus:
    """Return every stored risk input with its date and status.

    Args:
        db: Async DB session.
    """
    return await collect_inputs(db)


@router.put("/inputs", response_model=RiskInputsStatus)
async def put_risk_inputs(
    data: RiskInputsUpdate, db: AsyncSession = Depends(get_db)
) -> RiskInputsStatus:
    """Save the profile and any fresh measurements, then return the new status.

    Args:
        data: The validated risk form.
        db: Async DB session.
    """
    await save_inputs(db, data)
    return await collect_inputs(db)


@router.post("/calculate", response_model=RiskCalculationResponse)
async def calculate_risk(db: AsyncSession = Depends(get_db)) -> RiskCalculationResponse:
    """Compute the baseline scores from the stored inputs and persist them.

    A score whose inputs are missing is returned as ``None``; the response's
    ``inputs`` names what is missing.

    Args:
        db: Async DB session.
    """
    profile = await load_profile(db)
    scores = await compute_baseline_scores(db, profile)
    return RiskCalculationResponse(**scores, inputs=await collect_inputs(db))
