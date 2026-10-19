"""Tests for the risk-input status, saving, age derivation and validation."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from models.api_models import ProfileData, RiskInputsUpdate
from models.db_models import LabResult, SamsungHealthMetric, UserProfile, age_on
from services import risk_inputs
from services.risk_inputs import Measurement, collect_inputs, save_inputs

TODAY = date.today()


def _profile_data(**overrides) -> dict:
    base = dict(
        birth_year=1976, birth_month=5, sex="male", height_cm=178,
        smoking=False, bp_medication_ever=False, bp_medication_current=False,
        high_glucose_history=False, diabetes_diagnosed=False,
        vegetables_daily=True, physically_active=True, family_diabetes="none",
    )
    base.update(overrides)
    return base


# ── Age ──────────────────────────────────────────────────────────────────────

def test_age_counts_the_birth_month_as_birthday():
    """The age increases at the start of the birth month."""
    assert age_on(1980, 6, date(2026, 5, 31)) == 45
    assert age_on(1980, 6, date(2026, 6, 1)) == 46


def test_profile_age_property_uses_today():
    """The ORM age is derived from birth year and month, never stored."""
    profile = UserProfile(**_profile_data(birth_year=TODAY.year - 40, birth_month=1))
    assert profile.age == 40


# ── Validation ───────────────────────────────────────────────────────────────

def test_current_bp_medication_requires_ever():
    with pytest.raises(ValidationError):
        ProfileData(**_profile_data(bp_medication_current=True))


def test_diagnosed_diabetes_requires_high_glucose_history():
    with pytest.raises(ValidationError):
        ProfileData(**_profile_data(diabetes_diagnosed=True))


def test_birth_in_the_future_is_rejected():
    with pytest.raises(ValidationError):
        ProfileData(**_profile_data(birth_year=TODAY.year + 1))


def test_sex_must_be_male_or_female():
    with pytest.raises(ValidationError):
        ProfileData(**_profile_data(sex="other"))


def test_mmol_value_typed_as_mg_dl_is_rejected():
    """5.2 with mg/dL selected is almost surely mmol/L; refuse instead of scoring."""
    with pytest.raises(ValidationError):
        RiskInputsUpdate(
            profile=_profile_data(),
            total_cholesterol={"value": 5.2, "unit": "mg/dL", "test_date": TODAY},
        )


def test_mmol_value_with_mmol_unit_is_accepted():
    data = RiskInputsUpdate(
        profile=_profile_data(),
        total_cholesterol={"value": 5.2, "unit": "mmol/L", "test_date": TODAY},
    )
    assert data.total_cholesterol.unit == "mmol/L"


# ── Status ───────────────────────────────────────────────────────────────────

def _patch_reads(profile=None, labs=None, systolic=None, metrics=None):
    """Patch every reader used by collect_inputs."""
    labs = labs or {}
    metrics = metrics or {}

    async def lab(db, primary, fallback):
        return labs.get(primary)

    async def metric(db, metric_type):
        return metrics.get(metric_type)

    return [
        patch.object(risk_inputs, "load_profile", AsyncMock(return_value=profile)),
        patch.object(risk_inputs, "latest_lab", side_effect=lab),
        patch.object(risk_inputs, "latest_systolic", AsyncMock(return_value=systolic)),
        patch.object(risk_inputs, "latest_metric", side_effect=metric),
    ]


async def _collect(**reads):
    patches = _patch_reads(**reads)
    for p in patches:
        p.start()
    try:
        return await collect_inputs(AsyncMock())
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_empty_database_reports_everything_missing():
    status = await _collect()

    assert status.profile is None
    assert status.weight_kg.status == "missing"
    assert status.findrisc_missing == ["profile", "weight_kg", "waist_cm"]
    assert status.framingham_missing == [
        "profile", "systolic_bp", "total_cholesterol", "hdl_cholesterol"
    ]


@pytest.mark.asyncio
async def test_old_measurement_is_stale_but_still_usable():
    old = Measurement(80.0, "kg", TODAY - timedelta(days=200))
    fresh = Measurement(95.0, "cm", TODAY)
    status = await _collect(
        profile=UserProfile(**_profile_data()),
        metrics={"weight_kg": old, "waist_cm": fresh},
    )

    assert status.weight_kg.status == "stale"
    assert status.waist_cm.status == "ok"
    assert status.findrisc_missing == []
    assert status.age is not None


@pytest.mark.asyncio
async def test_lab_with_unknown_unit_is_unconvertible_and_missing():
    status = await _collect(labs={
        "total_cholesterol": Measurement(5.2, None, TODAY),
        "hdl_cholesterol": Measurement(1.3, "mmol/L", TODAY),
    })

    assert status.total_cholesterol.status == "unconvertible"
    assert status.hdl_cholesterol.status == "ok"
    assert "total_cholesterol" in status.framingham_missing


@pytest.mark.asyncio
async def test_female_profile_marks_framingham_unavailable():
    status = await _collect(profile=UserProfile(**_profile_data(sex="female")))
    assert status.framingham_unavailable is not None


# ── Saving ───────────────────────────────────────────────────────────────────

def _session() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_save_creates_profile_and_dated_measurements_in_one_commit():
    db = _session()
    data = RiskInputsUpdate(
        profile=_profile_data(),
        weight_kg=82.5,
        waist_cm=96,
        hdl_cholesterol={"value": 1.2, "unit": "mmol/L", "test_date": TODAY},
    )
    with patch.object(risk_inputs, "load_profile", AsyncMock(return_value=None)):
        await save_inputs(db, data)

    added = [call.args[0] for call in db.add.call_args_list]
    assert sum(isinstance(row, UserProfile) for row in added) == 1
    metrics = {row.metric_type: row for row in added if isinstance(row, SamsungHealthMetric)}
    assert set(metrics) == {"weight_kg", "waist_cm"}
    assert metrics["weight_kg"].source_file.startswith("manual_")
    labs = [row for row in added if isinstance(row, LabResult)]
    assert [(lab.test_name, lab.unit, lab.is_flagged) for lab in labs] == [
        ("hdl_cholesterol", "mmol/L", False)
    ]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_updates_existing_profile_and_keeps_omitted_measurements():
    db = _session()
    existing = UserProfile(**_profile_data())
    data = RiskInputsUpdate(profile=_profile_data(smoking=True, height_cm=180))
    with patch.object(risk_inputs, "load_profile", AsyncMock(return_value=existing)):
        await save_inputs(db, data)

    assert existing.smoking is True
    assert existing.height_cm == 180
    db.add.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_does_not_embed_manual_labs():
    """A typed lab value has no reference range, so no in/out-of-range text is embedded."""
    db = _session()
    data = RiskInputsUpdate(
        profile=_profile_data(),
        total_cholesterol={"value": 210, "unit": "mg/dL", "test_date": TODAY},
    )
    with patch.object(risk_inputs, "load_profile", AsyncMock(return_value=None)), \
         patch("services.rag_service.rag_service.embed_text", AsyncMock()) as embed:
        await save_inputs(db, data)

    embed.assert_not_called()


# ── Readers ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_latest_lab_falls_back_to_legacy_name():
    first, second = MagicMock(), MagicMock()
    first.fetchone.return_value = None
    second.fetchone.return_value = (5.0, "mmol/L", TODAY)
    db = AsyncMock()
    db.execute.side_effect = [first, second]

    found = await risk_inputs.latest_lab(db, "total_cholesterol", "cholesterol")

    assert found == Measurement(5.0, "mmol/L", TODAY)


def test_profile_data_reads_orm_row():
    """The GET status serialises the ORM row through ProfileData."""
    row = SimpleNamespace(**_profile_data())
    assert ProfileData.model_validate(row).family_diabetes == "none"
