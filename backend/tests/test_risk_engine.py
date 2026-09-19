"""Tests for RiskEngine — Framingham, FINDRISC, and BP classification."""
from __future__ import annotations

import pytest

from services.risk_engine import RiskEngine


@pytest.fixture
def engine():
    return RiskEngine()


# ── Framingham ────────────────────────────────────────────────────────────────

def test_framingham_low_risk_male(engine):
    """A 35-year-old non-smoking male with ideal values should score Low risk."""
    result = engine.calculate_framingham(
        age=35, sex="male",
        total_cholesterol=180, hdl_cholesterol=55,
        systolic_bp=115, bp_treated=False,
        diabetes=False, smoker=False,
    )
    assert result["risk_percent"] < 10
    assert result["risk_category"] == "Low (<10%)"


def test_framingham_high_risk_male(engine):
    """Older male smoker with high cholesterol and treated hypertension → High risk."""
    result = engine.calculate_framingham(
        age=62, sex="male",
        total_cholesterol=270, hdl_cholesterol=35,
        systolic_bp=155, bp_treated=True,
        diabetes=True, smoker=True,
    )
    assert result["risk_percent"] >= 20
    assert result["risk_category"] == "High (>20%)"


def test_framingham_returns_required_keys(engine):
    result = engine.calculate_framingham(
        age=50, sex="female",
        total_cholesterol=210, hdl_cholesterol=50,
        systolic_bp=130, bp_treated=False,
        diabetes=False, smoker=False,
    )
    assert {"score_points", "risk_percent", "risk_category"} == set(result.keys())


def test_framingham_rejects_mmol_l_total_cholesterol(engine):
    """A mmol/L-looking total cholesterol must raise instead of scoring wrongly."""
    with pytest.raises(ValueError, match="total_cholesterol"):
        engine.calculate_framingham(
            age=50, sex="male",
            total_cholesterol=5.2, hdl_cholesterol=50,
            systolic_bp=120, bp_treated=False,
            diabetes=False, smoker=False,
        )


def test_framingham_rejects_mmol_l_hdl(engine):
    """A mmol/L-looking HDL must raise instead of scoring wrongly."""
    with pytest.raises(ValueError, match="hdl_cholesterol"):
        engine.calculate_framingham(
            age=50, sex="male",
            total_cholesterol=200, hdl_cholesterol=1.3,
            systolic_bp=120, bp_treated=False,
            diabetes=False, smoker=False,
        )


# ── FINDRISC ──────────────────────────────────────────────────────────────────

def test_findrisc_low_score(engine):
    """Young, healthy, active person should score Low."""
    result = engine.calculate_findrisc(
        age=28, sex="male", waist_cm=85, bmi=22.0,
        physical_activity_mins_per_day=45,
        vegetables_daily=True,
        hypertension_medication=False,
        high_glucose_history=False,
        family_history_diabetes="none",
    )
    assert result["score"] < 7
    assert result["risk_category"] == "Low"


def test_findrisc_high_score(engine):
    """Older, obese, sedentary person with family history → Very High."""
    result = engine.calculate_findrisc(
        age=67, sex="female", waist_cm=95, bmi=33.0,
        physical_activity_mins_per_day=5,
        vegetables_daily=False,
        hypertension_medication=True,
        high_glucose_history=True,
        family_history_diabetes="first_degree",
    )
    assert result["score"] >= 15
    assert result["risk_category"] in ("High", "Very High")


def test_findrisc_returns_required_keys(engine):
    result = engine.calculate_findrisc(
        age=50, sex="male", waist_cm=105, bmi=27.0,
        physical_activity_mins_per_day=20,
        vegetables_daily=True,
        hypertension_medication=False,
        high_glucose_history=False,
    )
    assert {"score", "risk_category", "ten_year_risk_percent", "recommendation"} == set(result.keys())


# ── BP Classification ─────────────────────────────────────────────────────────

def test_bp_normal(engine):
    result = engine.classify_blood_pressure(115, 75)
    assert result["category"] == "Normal"
    assert result["specialist"] is None


def test_bp_elevated(engine):
    result = engine.classify_blood_pressure(125, 78)
    assert result["category"] == "Elevated"


def test_bp_stage1(engine):
    result = engine.classify_blood_pressure(135, 85)
    assert result["category"] == "Stage 1 Hypertension"


def test_bp_stage2(engine):
    result = engine.classify_blood_pressure(155, 95)
    assert result["category"] == "Stage 2 Hypertension"
    assert result["specialist"] == "Cardiologist"


def test_bp_crisis(engine):
    result = engine.classify_blood_pressure(185, 125)
    assert result["category"] == "Hypertensive Crisis"


@pytest.mark.parametrize(
    "systolic,diastolic,expected",
    [
        (119, 79, "Normal"),
        (120, 79, "Elevated"),
        (129, 79, "Elevated"),
        (119, 80, "Stage 1 Hypertension"),
        (130, 79, "Stage 1 Hypertension"),
        (139, 89, "Stage 1 Hypertension"),
        (140, 85, "Stage 2 Hypertension"),
        (135, 90, "Stage 2 Hypertension"),
        (160, 85, "Stage 2 Hypertension"),
        (179, 119, "Stage 2 Hypertension"),
        (180, 119, "Hypertensive Crisis"),
        (179, 120, "Hypertensive Crisis"),
        (185, 85, "Hypertensive Crisis"),
        (200, 100, "Hypertensive Crisis"),
    ],
)
def test_bp_category_boundaries(engine, systolic, diastolic, expected):
    """AHA category boundaries are evaluated most-severe-first."""
    assert engine.classify_blood_pressure(systolic, diastolic)["category"] == expected


def test_bp_high_systolic_with_low_diastolic_is_not_stage_1(engine):
    """Regression: a low diastolic must not downgrade a severe systolic value."""
    assert engine.classify_blood_pressure(185, 85)["category"] == "Hypertensive Crisis"
    assert engine.classify_blood_pressure(160, 85)["category"] == "Stage 2 Hypertension"
