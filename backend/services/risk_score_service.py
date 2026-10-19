"""Baseline Framingham and FINDRISC computation and persistence.

Single owner of baseline risk-score computation so the chat, recommendation
and risk routers share one implementation. Inputs are read through
``services.risk_inputs``. Hypothetical ("what if") recalculations are
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
from models.db_models import RiskScore, UserProfile
from services.risk_engine import risk_engine
from services.risk_inputs import (
    LAB_KEYS,
    WAIST_METRIC,
    WEIGHT_METRIC,
    latest_lab,
    latest_metric,
    latest_systolic,
)

logger = logging.getLogger(__name__)

# FINDRISC asks a yes/no question ("at least 30 minutes of physical activity
# daily?"), while risk_engine.calculate_findrisc takes minutes per day and adds
# points below 21 (= 150 min/week). The profile stores the answer, mapped to
# minutes here so the engine's threshold decides the points.
ACTIVE_MINS_PER_DAY = 30.0
INACTIVE_MINS_PER_DAY = 0.0

# FINDRISC waist cut-offs exist only for these two values.
FINDRISC_SEXES = frozenset({"male", "female"})

_EMPTY_SCORES: dict[str, Any] = {
    "framingham_risk_percent": None,
    "framingham_category": None,
    "findrisc_score": None,
    "findrisc_category": None,
}


# ── Input helpers ────────────────────────────────────────────────────────────

def activity_minutes(profile: Any) -> float:
    """Map the profile's yes/no activity answer to minutes per day."""
    if getattr(profile, "physically_active", False):
        return ACTIVE_MINS_PER_DAY
    return INACTIVE_MINS_PER_DAY


def bmi_from(weight_kg: Optional[float], height_cm: Optional[float]) -> Optional[float]:
    """Return the BMI, or ``None`` when weight or height is unknown."""
    if weight_kg is None or not height_cm:
        return None
    return weight_kg / ((height_cm / 100) ** 2)


def findrisc_missing(
    profile: Any, bmi: Optional[float], waist_cm: Optional[float]
) -> list[str]:
    """Return the FINDRISC inputs that are unknown.

    FINDRISC adds points for BMI and waist circumference; scoring without them
    would silently under-estimate the risk, so callers skip the score instead.

    Args:
        profile: The user profile, or ``None``.
        bmi: Body mass index, or ``None`` when weight or height is unknown.
        waist_cm: Waist circumference, or ``None`` when unknown.

    Returns:
        The names of the missing inputs; empty when the score can be computed.
    """
    if profile is None:
        return ["profile"]
    missing: list[str] = []
    if not getattr(profile, "age", None):
        missing.append("age")
    if getattr(profile, "sex", None) not in FINDRISC_SEXES:
        missing.append("sex (male/female)")
    if bmi is None:
        missing.append("bmi (weight and height)")
    if waist_cm is None:
        missing.append("waist_cm")
    return missing


async def _converted_lab(db: AsyncSession, canonical: str) -> Optional[tuple[float, str]]:
    """Fetch the latest lab value and convert it to mg/dL using its own unit.

    Args:
        db: Async database session.
        canonical: Normalised test name; also the key of ``LAB_KEYS``.

    Returns:
        ``(value_mg_dl, source_unit)`` or ``None`` when the value cannot be
        fetched or its unit cannot be converted without guessing.
    """
    row = await latest_lab(db, *LAB_KEYS[canonical])
    if row is None:
        return None
    converted = lab_unit_converter.to_mg_dl(canonical, row.value, row.unit)
    if converted is None:
        return None
    return converted, (row.unit or "unknown")


async def _latest_value(db: AsyncSession, metric_type: str) -> Optional[float]:
    """Return the latest value of a measurement, or ``None``."""
    measurement = await latest_metric(db, metric_type)
    return measurement.value if measurement is not None else None


async def _latest_systolic(db: AsyncSession) -> Optional[int]:
    """Return the most recent systolic reading in mmHg, or ``None``."""
    measurement = await latest_systolic(db)
    return int(measurement.value) if measurement is not None else None


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
    if not risk_engine.framingham_supported(profile.sex):
        logger.warning(
            "Framingham skipped: %s.", risk_engine.FRAMINGHAM_UNSUPPORTED_REASON
        )
        return None

    tc_value, tc_unit = total_cholesterol
    hdl_value, hdl_unit = hdl_cholesterol
    bp_treated = bool(getattr(profile, "bp_medication_current", False))
    diabetes = bool(getattr(profile, "diabetes_diagnosed", False))
    smoker = bool(getattr(profile, "smoking", False))
    result = risk_engine.calculate_framingham(
        age=profile.age,
        sex=profile.sex,
        total_cholesterol=tc_value,
        hdl_cholesterol=hdl_value,
        systolic_bp=systolic_bp,
        bp_treated=bp_treated,
        diabetes=diabetes,
        smoker=smoker,
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
            "bp_treated": bp_treated,
            "diabetes": diabetes,
            "smoker": smoker,
        },
    }


def _compute_findrisc(
    profile: UserProfile, weight_kg: Optional[float], waist_cm: Optional[float]
) -> Optional[dict[str, Any]]:
    """Compute the FINDRISC payload, or ``None`` when an input is missing.

    Missing inputs are logged at warning level; no defaults are substituted.
    """
    bmi = bmi_from(weight_kg, getattr(profile, "height_cm", None))
    missing = findrisc_missing(profile, bmi, waist_cm)
    if missing:
        logger.warning("FINDRISC skipped: missing %s.", ", ".join(missing))
        return None

    inputs = {
        "age": profile.age,
        "sex": profile.sex,
        "waist_cm": waist_cm,
        "bmi": bmi,
        "physical_activity_mins_per_day": activity_minutes(profile),
        "vegetables_daily": bool(getattr(profile, "vegetables_daily", False)),
        "hypertension_medication": bool(getattr(profile, "bp_medication_ever", False)),
        "high_glucose_history": bool(getattr(profile, "high_glucose_history", False)),
        "family_history_diabetes": getattr(profile, "family_diabetes", None) or "none",
    }
    result = risk_engine.calculate_findrisc(**inputs)
    return {
        "score_type": "findrisc",
        "score_value": float(result["score"]),
        "risk_category": result["risk_category"],
        "inputs": {**inputs, "bmi": round(bmi, 2)},
    }


def _compute_baseline_scores(
    profile: UserProfile,
    total_cholesterol: Optional[tuple[float, str]],
    hdl_cholesterol: Optional[tuple[float, str]],
    systolic_bp: Optional[int],
    weight_kg: Optional[float],
    waist_cm: Optional[float],
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

    findrisc = _compute_findrisc(profile, weight_kg, waist_cm)
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

    total_cholesterol = await _converted_lab(db, "total_cholesterol")
    hdl_cholesterol = await _converted_lab(db, "hdl_cholesterol")
    systolic_bp = await _latest_systolic(db)
    weight_kg = await _latest_value(db, WEIGHT_METRIC)
    waist_cm = await _latest_value(db, WAIST_METRIC)

    result, payloads = _compute_baseline_scores(
        profile, total_cholesterol, hdl_cholesterol, systolic_bp, weight_kg, waist_cm
    )
    await _persist_scores(db, payloads)
    return result
