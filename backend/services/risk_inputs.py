"""Risk-score inputs: read what is stored, report what is missing, save new values.

Single owner of the inputs the FINDRISC and Framingham calculations read:
the ``user_profile`` row, the latest weight and waist measurements
(``samsung_health_metrics``), the latest systolic blood pressure and the
latest total and HDL cholesterol (``lab_results``). Everything is stored in
SQL only; nothing here is embedded for RAG, because the scores need exact,
dated values with units, and the chat prompt receives them directly.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from ingestion.unit_converter import lab_unit_converter
from models.api_models import (
    ManualLabValue,
    ProfileData,
    RiskInputsStatus,
    RiskInputsUpdate,
    StoredInput,
)
from models.db_models import (
    BloodPressureReading,
    LabResult,
    SamsungHealthMetric,
    UserProfile,
)
from services.risk_engine import risk_engine

logger = logging.getLogger(__name__)

WEIGHT_METRIC = "weight_kg"
WAIST_METRIC = "waist_cm"

# Lab keys the scores read: (canonical, legacy fallback). The fallback names
# come from older parser versions and are read only when the canonical key
# has no rows.
LAB_KEYS: dict[str, tuple[str, str]] = {
    "total_cholesterol": ("total_cholesterol", "cholesterol"),
    "hdl_cholesterol": ("hdl_cholesterol", "hdl"),
}

# Report names stored for cholesterol typed into the risk form, so the chat's
# lab summary shows where the value came from.
MANUAL_LAB_NAMES: dict[str, str] = {
    "total_cholesterol": "Összkoleszterin (kézi bevitel / manual entry)",
    "hdl_cholesterol": "HDL-koleszterin (kézi bevitel / manual entry)",
}


@dataclass(frozen=True)
class Measurement:
    """The latest stored value of one input."""

    value: float
    unit: Optional[str]
    recorded_on: Optional[date]


# ── Reading ──────────────────────────────────────────────────────────────────

async def load_profile(db: AsyncSession) -> Optional[UserProfile]:
    """Return the single user profile, or ``None`` when none exists."""
    result = await db.execute(select(UserProfile).limit(1))
    return result.scalar_one_or_none()


async def latest_lab(
    db: AsyncSession, primary: str, fallback: str
) -> Optional[Measurement]:
    """Return the latest dated lab row for ``primary``, else for ``fallback``."""
    for test_name in (primary, fallback):
        result = await db.execute(
            select(LabResult.value, LabResult.unit, LabResult.test_date)
            .where(LabResult.test_name == test_name)
            .where(LabResult.test_date.isnot(None))
            .order_by(LabResult.test_date.desc())
            .limit(1)
        )
        row = result.fetchone()
        if row is not None:
            return Measurement(float(row[0]), row[1], row[2])
    return None


async def latest_systolic(db: AsyncSession) -> Optional[Measurement]:
    """Return the most recent systolic blood pressure in mmHg."""
    result = await db.execute(
        select(BloodPressureReading.systolic, BloodPressureReading.measured_at)
        .order_by(BloodPressureReading.measured_at.desc())
        .limit(1)
    )
    row = result.fetchone()
    if row is None:
        return None
    return Measurement(float(row[0]), "mmHg", _as_date(row[1]))


async def latest_metric(db: AsyncSession, metric_type: str) -> Optional[Measurement]:
    """Return the most recent measurement of ``metric_type``."""
    result = await db.execute(
        select(SamsungHealthMetric.value, SamsungHealthMetric.recorded_at)
        .where(SamsungHealthMetric.metric_type == metric_type)
        .order_by(SamsungHealthMetric.recorded_at.desc())
        .limit(1)
    )
    row = result.fetchone()
    if row is None:
        return None
    unit = "kg" if metric_type == WEIGHT_METRIC else "cm"
    return Measurement(float(row[0]), unit, _as_date(row[1]))


def _as_date(value: object) -> Optional[date]:
    """Return the date part of a datetime, or the value if it is a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


# ── Status ───────────────────────────────────────────────────────────────────

def _status(
    measurement: Optional[Measurement], stale_days: int, today: date
) -> StoredInput:
    """Describe one stored measurement as ok, stale or missing."""
    if measurement is None:
        return StoredInput()
    stale = (
        measurement.recorded_on is not None
        and today - measurement.recorded_on > timedelta(days=stale_days)
    )
    return StoredInput(
        value=measurement.value,
        unit=measurement.unit,
        recorded_on=measurement.recorded_on,
        status="stale" if stale else "ok",
    )


def _lab_status(
    canonical: str, measurement: Optional[Measurement], today: date
) -> StoredInput:
    """Describe a stored lab value; a unit that cannot be converted is unusable."""
    stored = _status(measurement, settings.risk_lab_stale_days, today)
    if measurement is not None and lab_unit_converter.to_mg_dl(
        canonical, measurement.value, measurement.unit
    ) is None:
        stored.status = "unconvertible"
    return stored


def missing_inputs(status: RiskInputsStatus) -> tuple[list[str], list[str]]:
    """Return the inputs FINDRISC and Framingham still lack.

    Args:
        status: The stored inputs, with ``findrisc_missing`` and
            ``framingham_missing`` not yet filled in.

    Returns:
        ``(findrisc_missing, framingham_missing)`` as lists of input names.
    """
    usable = {"ok", "stale"}
    findrisc: list[str] = []
    framingham: list[str] = []
    if status.profile is None:
        findrisc.append("profile")
        framingham.append("profile")
    for name in ("weight_kg", "waist_cm"):
        if getattr(status, name).status not in usable:
            findrisc.append(name)
    for name in ("systolic_bp", "total_cholesterol", "hdl_cholesterol"):
        if getattr(status, name).status not in usable:
            framingham.append(name)
    return findrisc, framingham


async def collect_inputs(db: AsyncSession) -> RiskInputsStatus:
    """Read every stored risk input and report what each score still needs.

    Args:
        db: Async database session.

    Returns:
        The stored values with their dates and status, the inputs each score
        lacks, and why Framingham is unavailable when the profile rules it out.
    """
    today = date.today()
    profile = await load_profile(db)
    measurement_days = settings.risk_measurement_stale_days
    labs = {
        name: _lab_status(name, await latest_lab(db, *keys), today)
        for name, keys in LAB_KEYS.items()
    }
    status = RiskInputsStatus(
        profile=ProfileData.model_validate(profile) if profile else None,
        age=profile.age if profile else None,
        weight_kg=_status(await latest_metric(db, WEIGHT_METRIC), measurement_days, today),
        waist_cm=_status(await latest_metric(db, WAIST_METRIC), measurement_days, today),
        systolic_bp=_status(await latest_systolic(db), measurement_days, today),
        total_cholesterol=labs["total_cholesterol"],
        hdl_cholesterol=labs["hdl_cholesterol"],
        findrisc_missing=[],
        framingham_missing=[],
    )
    status.findrisc_missing, status.framingham_missing = missing_inputs(status)
    if profile is not None and not risk_engine.framingham_supported(str(profile.sex)):
        status.framingham_unavailable = risk_engine.FRAMINGHAM_UNSUPPORTED_REASON
    return status


# ── Saving ───────────────────────────────────────────────────────────────────

def manual_source_id() -> str:
    """Generate the identifier stored as the source of a manual entry."""
    return f"manual_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}"


async def _upsert_profile(db: AsyncSession, data: ProfileData) -> None:
    """Update the single profile row, or create it when none exists."""
    profile = await load_profile(db)
    if profile is None:
        db.add(UserProfile(**data.model_dump()))
        return
    for field, value in data.model_dump().items():
        setattr(profile, field, value)


def _add_metric(db: AsyncSession, metric_type: str, value: float, source: str) -> None:
    """Add one manually entered measurement, timestamped now."""
    db.add(
        SamsungHealthMetric(
            metric_type=metric_type,
            value=value,
            recorded_at=datetime.now(timezone.utc),
            source_file=source,
        )
    )


def _add_lab(db: AsyncSession, name: str, lab: ManualLabValue, source: str) -> None:
    """Add one manually entered cholesterol value with its unit.

    No reference range is known for a typed value, so the row is not flagged
    and is not embedded: an embedded lab text states whether the value is in
    range, which would be a guess here.
    """
    db.add(
        LabResult(
            test_name=name,
            raw_name=MANUAL_LAB_NAMES[name],
            value=lab.value,
            unit=lab.unit,
            ref_range_low=None,
            ref_range_high=None,
            is_flagged=False,
            test_date=lab.test_date,
            source_filename=source,
        )
    )


async def save_inputs(db: AsyncSession, data: RiskInputsUpdate) -> None:
    """Save the risk form in one transaction.

    The profile is upserted; a fresh weight, waist or cholesterol value is
    added as a new dated row, so earlier values stay as history. Values left
    out of the form keep the stored ones.

    Args:
        db: Async database session; committed once at the end.
        data: The validated form payload.
    """
    source = manual_source_id()
    await _upsert_profile(db, data.profile)
    if data.weight_kg is not None:
        _add_metric(db, WEIGHT_METRIC, data.weight_kg, source)
    if data.waist_cm is not None:
        _add_metric(db, WAIST_METRIC, data.waist_cm, source)
    for name in LAB_KEYS:
        lab = getattr(data, name)
        if lab is not None:
            _add_lab(db, name, lab, source)
    await db.commit()
    logger.info("Saved risk inputs (source %s).", source)
