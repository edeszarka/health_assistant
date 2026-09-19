"""Baseline Framingham and FINDRISC computation and persistence.

Single owner of baseline risk-score computation so the chat and recommendation
routers share one implementation. Hypothetical ("what if") recalculations are
deliberately NOT handled here — they are not measurements and must never be
persisted.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ingestion.unit_converter import lab_unit_converter
from models.db_models import (
    BloodPressureReading,
    LabResult,
    RiskScore,
    SamsungHealthMetric,
    UserProfile,
)
from services.risk_engine import risk_engine

logger = logging.getLogger(__name__)

# chat.py has always assumed a fixed 30 minutes of daily activity because no
# derivation from wearable step data exists yet.
# TODO: derive physical_activity_mins_per_day from SamsungHealthMetric step
# data instead of hard-coding this value.
DEFAULT_PHYSICAL_ACTIVITY_MINS_PER_DAY = 30.0

_EMPTY_SCORES: dict[str, Any] = {
    "framingham_risk_percent": None,
    "framingham_category": None,
    "findrisc_score": None,
    "findrisc_category": None,
}


# ── Input fetching ───────────────────────────────────────────────────────────

async def _latest_lab_row(
    db: AsyncSession, primary: str, fallback: str
) -> Optional[tuple[float, Optional[str]]]:
    """Return ``(value, unit)`` for the latest primary test, else the fallback.

    Args:
        db: Async database session.
        primary: Preferred normalised test name.
        fallback: Legacy test name used only when the primary has no rows.

    Returns:
        A ``(value, unit)`` tuple, or ``None`` when neither test is present.
    """
    for test_name in (primary, fallback):
        result = await db.execute(
            select(LabResult.value, LabResult.unit)
            .where(LabResult.test_name == test_name)
            .where(LabResult.test_date.isnot(None))
            .order_by(LabResult.test_date.desc())
            .limit(1)
        )
        row = result.fetchone()
        if row is not None:
            return float(row[0]), row[1]
    return None


async def _converted_lab(
    db: AsyncSession, canonical: str, primary: str, fallback: str
) -> Optional[tuple[float, str]]:
    """Fetch a lab value and convert it to mg/dL using the row's own unit.

    Args:
        db: Async database session.
        canonical: Normalised test name used for the conversion factor.
        primary: Preferred normalised test name.
        fallback: Legacy test name used only when the primary has no rows.

    Returns:
        ``(value_mg_dl, source_unit)`` or ``None`` when the value cannot be
        fetched or its unit cannot be converted without guessing.
    """
    row = await _latest_lab_row(db, primary, fallback)
    if row is None:
        return None
    value, unit = row
    converted = lab_unit_converter.to_mg_dl(canonical, value, unit)
    if converted is None:
        return None
    return converted, (unit or "unknown")


async def _latest_systolic(db: AsyncSession) -> Optional[int]:
    """Return the most recent systolic reading in mmHg, or ``None``."""
    result = await db.execute(
        select(BloodPressureReading.systolic)
        .order_by(BloodPressureReading.measured_at.desc())
        .limit(1)
    )
    row = result.fetchone()
    return int(row[0]) if row is not None else None


async def _latest_weight_kg(db: AsyncSession) -> Optional[float]:
    """Return the most recent weight measurement in kg, or ``None``."""
    result = await db.execute(
        select(SamsungHealthMetric.value)
        .where(SamsungHealthMetric.metric_type == "weight_kg")
        .order_by(SamsungHealthMetric.recorded_at.desc())
        .limit(1)
    )
    row = result.fetchone()
    return float(row[0]) if row is not None else None


# ── Computation ──────────────────────────────────────────────────────────────

def _compute_framingham(
    profile: UserProfile,
    total_cholesterol: Optional[tuple[float, str]],
    hdl_cholesterol: Optional[tuple[float, str]],
    systolic_bp: Optional[int],
) -> Optional[dict[str, Any]]:
    """Compute the Framingham payload, or ``None`` when inputs are missing.

    Missing inputs are logged at warning level; no defaults are substituted.
    """
    missing: list[str] = []
    if not getattr(profile, "age", None):
        missing.append("age")
    if not getattr(profile, "sex", None):
        missing.append("sex")
    if total_cholesterol is None:
        missing.append("total_cholesterol (mg/dL)")
    if hdl_cholesterol is None:
        missing.append("hdl_cholesterol (mg/dL)")
    if systolic_bp is None:
        missing.append("systolic_bp")
    if missing:
        logger.warning("Framingham skipped: missing %s.", ", ".join(missing))
        return None

    tc_value, tc_unit = total_cholesterol
    hdl_value, hdl_unit = hdl_cholesterol
    result = risk_engine.calculate_framingham(
        age=profile.age,
        sex=profile.sex,
        total_cholesterol=tc_value,
        hdl_cholesterol=hdl_value,
        systolic_bp=systolic_bp,
        bp_treated=bool(getattr(profile, "bp_medication", False)),
        diabetes=bool(getattr(profile, "high_glucose_history", False)),
        smoker=bool(getattr(profile, "smoking", False)),
    )
    return {
        "score_type": "framingham",
        "score_value": float(result["risk_percent"]),
        "risk_category": result["risk_category"],
        "inputs": {
            "age": profile.age,
            "sex": profile.sex,
            "total_cholesterol_mg_dl": round(tc_value, 2),
            "total_cholesterol_source_unit": tc_unit,
            "hdl_cholesterol_mg_dl": round(hdl_value, 2),
            "hdl_cholesterol_source_unit": hdl_unit,
            "systolic_bp": systolic_bp,
            "bp_treated": bool(getattr(profile, "bp_medication", False)),
            "diabetes": bool(getattr(profile, "high_glucose_history", False)),
            "smoker": bool(getattr(profile, "smoking", False)),
        },
    }


def _compute_findrisc(
    profile: UserProfile, weight_kg: Optional[float]
) -> Optional[dict[str, Any]]:
    """Compute the FINDRISC payload, or ``None`` when no profile is available."""
    if profile is None:
        return None

    bmi = None
    if weight_kg is not None and getattr(profile, "height_cm", None):
        bmi = weight_kg / ((profile.height_cm / 100) ** 2)

    family_history_diabetes = (
        "first_degree" if getattr(profile, "family_diabetes", False) else "none"
    )
    result = risk_engine.calculate_findrisc(
        age=profile.age,
        sex=profile.sex,
        waist_cm=getattr(profile, "waist_cm", None),
        bmi=bmi,
        physical_activity_mins_per_day=DEFAULT_PHYSICAL_ACTIVITY_MINS_PER_DAY,
        vegetables_daily=bool(getattr(profile, "vegetables_daily", False)),
        hypertension_medication=bool(getattr(profile, "bp_medication", False)),
        high_glucose_history=bool(getattr(profile, "high_glucose_history", False)),
        family_history_diabetes=family_history_diabetes,
    )
    return {
        "score_type": "findrisc",
        "score_value": float(result["score"]),
        "risk_category": result["risk_category"],
        "inputs": {
            "age": profile.age,
            "sex": profile.sex,
            "waist_cm": getattr(profile, "waist_cm", None),
            "bmi": round(bmi, 2) if bmi is not None else None,
            "physical_activity_mins_per_day": DEFAULT_PHYSICAL_ACTIVITY_MINS_PER_DAY,
            "vegetables_daily": bool(getattr(profile, "vegetables_daily", False)),
            "hypertension_medication": bool(getattr(profile, "bp_medication", False)),
            "high_glucose_history": bool(
                getattr(profile, "high_glucose_history", False)
            ),
            "family_history_diabetes": family_history_diabetes,
        },
    }


def _compute_baseline_scores(
    profile: UserProfile,
    total_cholesterol: Optional[tuple[float, str]],
    hdl_cholesterol: Optional[tuple[float, str]],
    systolic_bp: Optional[int],
    weight_kg: Optional[float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compute all baseline scores without touching the database.

    Returns:
        A ``(result, payloads)`` tuple where ``result`` holds the public
        values (``None`` when a score could not be computed) and ``payloads``
        holds the persistence payloads for the scores that succeeded.
    """
    result = dict(_EMPTY_SCORES)
    payloads: list[dict[str, Any]] = []

    framingham = _compute_framingham(
        profile, total_cholesterol, hdl_cholesterol, systolic_bp
    )
    if framingham is not None:
        result["framingham_risk_percent"] = framingham["score_value"]
        result["framingham_category"] = framingham["risk_category"]
        payloads.append(framingham)

    findrisc = _compute_findrisc(profile, weight_kg)
    if findrisc is not None:
        result["findrisc_score"] = int(findrisc["score_value"])
        result["findrisc_category"] = findrisc["risk_category"]
        payloads.append(findrisc)

    return result, payloads


# ── Persistence ──────────────────────────────────────────────────────────────

async def _persist_score(db: AsyncSession, payload: dict[str, Any]) -> bool:
    """Insert a RiskScore row unless the latest one is unchanged.

    Returns:
        ``True`` when a new row was added, ``False`` when the insert was
        skipped because the value and category match the latest row.
    """
    result = await db.execute(
        select(RiskScore)
        .where(RiskScore.score_type == payload["score_type"])
        .order_by(RiskScore.calculated_at.desc())
        .limit(1)
    )
    row = result.fetchone()
    latest = row[0] if row is not None else None
    if (
        latest is not None
        and latest.score_value == payload["score_value"]
        and latest.risk_category == payload["risk_category"]
    ):
        logger.info("Skipping unchanged %s score.", payload["score_type"])
        return False

    db.add(
        RiskScore(
            score_type=payload["score_type"],
            score_value=payload["score_value"],
            risk_category=payload["risk_category"],
            inputs_json=json.dumps(payload["inputs"]),
        )
    )
    return True


async def _persist_scores(db: AsyncSession, payloads: list[dict[str, Any]]) -> None:
    """Persist every payload, committing once if anything was inserted."""
    inserted = False
    for payload in payloads:
        if await _persist_score(db, payload):
            inserted = True
    if inserted:
        await db.commit()


# ── Public API ───────────────────────────────────────────────────────────────

async def compute_baseline_scores(
    db: AsyncSession, profile: Optional[UserProfile]
) -> dict[str, Any]:
    """Compute, persist, and return the baseline Framingham and FINDRISC scores.

    Args:
        db: Async database session.
        profile: The single user profile, or ``None`` when none exists.

    Returns:
        Dict with ``framingham_risk_percent``, ``framingham_category``,
        ``findrisc_score`` and ``findrisc_category``. Each is ``None`` when the
        required inputs are unavailable.
    """
    if profile is None:
        return dict(_EMPTY_SCORES)

    total_cholesterol = await _converted_lab(
        db, "total_cholesterol", "total_cholesterol", "cholesterol"
    )
    hdl_cholesterol = await _converted_lab(
        db, "hdl_cholesterol", "hdl_cholesterol", "hdl"
    )
    systolic_bp = await _latest_systolic(db)
    weight_kg = await _latest_weight_kg(db)

    result, payloads = _compute_baseline_scores(
        profile, total_cholesterol, hdl_cholesterol, systolic_bp, weight_kg
    )
    await _persist_scores(db, payloads)
    return result
