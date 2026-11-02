"""Exact checks of the risk calculators against the published point tables.

Expected values are transcribed from the tables, not computed from the code:

- Framingham, men: NCEP ATP III point score (Third Report, 2001; NHLBI "Estimate
  of 10-Year Risk for CHD").
- FINDRISC: Lindström J, Tuomilehto J. The Diabetes Risk Score. Diabetes Care
  2003;26(3):725-731.

These are table checks. The sources contain no worked patient examples that
were used here.
"""
from __future__ import annotations

import pytest

from services.risk_engine import RiskEngine


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine()


def _framingham(engine: RiskEngine, **overrides) -> dict:
    """Framingham with inputs that add 0 points, apart from age and overrides."""
    inputs = dict(
        age=40, sex="male", total_cholesterol=150, hdl_cholesterol=55,
        systolic_bp=110, bp_treated=False, smoker=False,
    )
    inputs.update(overrides)
    return engine.calculate_framingham(**inputs)


def _findrisc_score(engine: RiskEngine, **overrides) -> dict:
    """FINDRISC with inputs that add 0 points, apart from the overrides."""
    inputs = dict(
        age=40, sex="male", waist_cm=80, bmi=22,
        physical_activity_mins_per_day=30, vegetables_daily=True,
        hypertension_medication=False, high_glucose_history=False,
        family_history_diabetes="none",
    )
    inputs.update(overrides)
    return engine.calculate_findrisc(**inputs)


# ── Framingham: one factor at a time ─────────────────────────────────────────

@pytest.mark.parametrize(
    ("age", "points"),
    [
        (20, -9), (34, -9), (35, -4), (39, -4), (40, 0), (44, 0), (45, 3), (49, 3),
        (50, 6), (54, 6), (55, 8), (59, 8), (60, 10), (64, 10), (65, 11), (69, 11),
        (70, 12), (74, 12), (75, 13), (79, 13),
    ],
)
def test_framingham_age_points(engine, age, points):
    assert _framingham(engine, age=age)["score_points"] == points


@pytest.mark.parametrize(
    ("age", "age_points", "band_points"),
    [
        (30, -9, (0, 4, 7, 9, 11)),
        (45, 3, (0, 3, 5, 6, 8)),
        (55, 8, (0, 2, 3, 4, 5)),
        (65, 11, (0, 1, 1, 2, 3)),
        (72, 12, (0, 0, 0, 1, 1)),
    ],
)
def test_framingham_total_cholesterol_points(engine, age, age_points, band_points):
    # Both ends of each band: <160, 160-199, 200-239, 240-279, >=280.
    bands = ((50, 159), (160, 199), (200, 239), (240, 279), (280, 400))
    for (low, high), points in zip(bands, band_points):
        for total_cholesterol in (low, high):
            result = _framingham(engine, age=age, total_cholesterol=total_cholesterol)
            assert result["score_points"] == age_points + points


@pytest.mark.parametrize(
    ("hdl", "points"),
    [(60, -1), (90, -1), (59, 0), (50, 0), (49, 1), (40, 1), (39, 2), (10, 2)],
)
def test_framingham_hdl_points(engine, hdl, points):
    assert _framingham(engine, hdl_cholesterol=hdl)["score_points"] == points


@pytest.mark.parametrize(
    ("systolic", "untreated", "treated"),
    [
        (119, 0, 0), (120, 0, 1), (129, 0, 1), (130, 1, 2), (139, 1, 2),
        (140, 1, 2), (159, 1, 2), (160, 2, 3), (200, 2, 3),
    ],
)
def test_framingham_systolic_points(engine, systolic, untreated, treated):
    assert _framingham(engine, systolic_bp=systolic)["score_points"] == untreated
    assert (
        _framingham(engine, systolic_bp=systolic, bp_treated=True)["score_points"]
        == treated
    )


@pytest.mark.parametrize(
    ("age", "age_points", "smoker_points"),
    [
        (20, -9, 8), (39, -4, 8), (40, 0, 5), (49, 3, 5), (50, 6, 3), (59, 8, 3),
        (60, 10, 1), (69, 11, 1), (70, 12, 1), (79, 13, 1),
    ],
)
def test_framingham_smoker_points_depend_on_age(engine, age, age_points, smoker_points):
    result = _framingham(engine, age=age, smoker=True)
    assert result["score_points"] == age_points + smoker_points


# ── Framingham: points to risk ───────────────────────────────────────────────

@pytest.mark.parametrize(
    ("points", "percent", "category"),
    [
        (1, 1.0, "Low (<10%)"), (4, 1.0, "Low (<10%)"), (5, 2.0, "Low (<10%)"),
        (6, 2.0, "Low (<10%)"), (7, 3.0, "Low (<10%)"), (8, 4.0, "Low (<10%)"),
        (9, 5.0, "Low (<10%)"), (10, 6.0, "Low (<10%)"), (11, 8.0, "Low (<10%)"),
        (12, 10.0, "Moderate (10-20%)"), (13, 12.0, "Moderate (10-20%)"),
        (14, 16.0, "Moderate (10-20%)"), (15, 20.0, "Moderate (10-20%)"),
        (16, 25.0, "High (>20%)"), (17, 30.0, "High (30% or more)"),
        (25, 30.0, "High (30% or more)"),
    ],
)
def test_framingham_points_to_risk(engine, points, percent, category):
    assert engine._framingham_risk(points) == (percent, category)


@pytest.mark.parametrize("points", [0, -1, -9])
def test_framingham_below_one_percent_is_stored_as_one(engine, points):
    """The table's "<1%" row is stored as 1, the nearest number."""
    assert engine._framingham_risk(points) == (1.0, "Low (<10%)")


# ── Framingham: whole cases, summed by hand from the table ───────────────────

@pytest.mark.parametrize(
    ("inputs", "points", "percent", "category"),
    [
        # 8 age + 3 cholesterol
        (dict(age=55, smoker=False), 11, 8.0, "Low (<10%)"),
        # 8 age + 3 cholesterol + 3 smoker
        (dict(age=55, smoker=True), 14, 16.0, "Moderate (10-20%)"),
        # 11 age + 1 cholesterol + 1 smoker
        (dict(age=65, smoker=True), 13, 12.0, "Moderate (10-20%)"),
        # 12 age + 1 cholesterol + 2 HDL + 3 treated systolic
        (
            dict(age=72, smoker=False, total_cholesterol=290, hdl_cholesterol=35,
                 systolic_bp=170, bp_treated=True),
            18, 30.0, "High (30% or more)",
        ),
    ],
)
def test_framingham_whole_cases(engine, inputs, points, percent, category):
    base = dict(sex="male", total_cholesterol=213, hdl_cholesterol=50,
                systolic_bp=120, bp_treated=False)
    result = engine.calculate_framingham(**{**base, **inputs})
    assert result == {
        "score_points": points, "risk_percent": percent, "risk_category": category,
    }


# ── Framingham: when the table does not apply ────────────────────────────────

@pytest.mark.parametrize(
    ("sex", "diabetes", "age", "reason"),
    [
        ("male", False, 50, None),
        ("Male", False, 20, None),
        ("male", False, 79, None),
        ("male", False, None, None),
        ("female", False, 50, RiskEngine.FRAMINGHAM_MEN_ONLY_REASON),
        (None, False, 50, RiskEngine.FRAMINGHAM_MEN_ONLY_REASON),
        ("", False, 50, RiskEngine.FRAMINGHAM_MEN_ONLY_REASON),
        ("male", True, 50, RiskEngine.FRAMINGHAM_DIABETES_REASON),
        ("male", False, 19, RiskEngine.FRAMINGHAM_AGE_REASON),
        ("male", False, 80, RiskEngine.FRAMINGHAM_AGE_REASON),
    ],
)
def test_framingham_unavailable_reason(sex, diabetes, age, reason):
    assert RiskEngine.framingham_unavailable_reason(sex, diabetes, age) == reason


@pytest.mark.parametrize(
    "overrides", [dict(sex="female"), dict(age=19), dict(age=80)],
)
def test_calculate_framingham_refuses_where_the_table_does_not_apply(engine, overrides):
    with pytest.raises(ValueError, match="No Framingham score"):
        _framingham(engine, **overrides)


# ── FINDRISC: one item at a time ─────────────────────────────────────────────

@pytest.mark.parametrize(
    ("overrides", "points"),
    [
        (dict(age=44), 0), (dict(age=45), 2), (dict(age=54), 2), (dict(age=55), 3),
        (dict(age=64), 3), (dict(age=65), 4),
        (dict(bmi=24.9), 0), (dict(bmi=25), 1), (dict(bmi=30), 1), (dict(bmi=30.1), 3),
        (dict(waist_cm=93), 0), (dict(waist_cm=94), 3), (dict(waist_cm=102), 3),
        (dict(waist_cm=103), 4),
        (dict(sex="female", waist_cm=79), 0), (dict(sex="female", waist_cm=80), 3),
        (dict(sex="female", waist_cm=88), 3), (dict(sex="female", waist_cm=89), 4),
        (dict(physical_activity_mins_per_day=0), 2),
        (dict(vegetables_daily=False), 1),
        (dict(hypertension_medication=True), 2),
        (dict(high_glucose_history=True), 5),
        (dict(family_history_diabetes="second_degree"), 3),
        (dict(family_history_diabetes="first_degree"), 5),
    ],
)
def test_findrisc_item_points(engine, overrides, points):
    assert _findrisc_score(engine, **overrides)["score"] == points


# ── FINDRISC: score bands ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("overrides", "score", "category", "percent"),
    [
        # age 4 + activity 2
        (dict(age=65, physical_activity_mins_per_day=0), 6, "Low", 1.0),
        # age 4 + activity 2 + vegetables 1
        (dict(age=65, physical_activity_mins_per_day=0, vegetables_daily=False),
         7, "Slightly elevated", 4.0),
        # age 4 + waist 3 + activity 2 + medication 2
        (dict(age=65, waist_cm=94, physical_activity_mins_per_day=0,
              hypertension_medication=True), 11, "Slightly elevated", 4.0),
        # age 4 + waist 4 + activity 2 + medication 2
        (dict(age=65, waist_cm=103, physical_activity_mins_per_day=0,
              hypertension_medication=True), 12, "Moderate", 17.0),
        # age 4 + BMI 3 + waist 3 + activity 2 + medication 2
        (dict(age=65, bmi=31, waist_cm=94, physical_activity_mins_per_day=0,
              hypertension_medication=True), 14, "Moderate", 17.0),
        # age 4 + BMI 3 + waist 4 + activity 2 + medication 2
        (dict(age=65, bmi=31, waist_cm=103, physical_activity_mins_per_day=0,
              hypertension_medication=True), 15, "High", 33.0),
        # age 4 + BMI 3 + waist 4 + activity 2 + medication 2 + family 5
        (dict(age=65, bmi=31, waist_cm=103, physical_activity_mins_per_day=0,
              hypertension_medication=True, family_history_diabetes="first_degree"),
         20, "High", 33.0),
        # the same + vegetables 1
        (dict(age=65, bmi=31, waist_cm=103, physical_activity_mins_per_day=0,
              hypertension_medication=True, family_history_diabetes="first_degree",
              vegetables_daily=False), 21, "Very High", 50.0),
    ],
)
def test_findrisc_score_bands(engine, overrides, score, category, percent):
    result = _findrisc_score(engine, **overrides)
    assert result["score"] == score
    assert result["risk_category"] == category
    assert result["ten_year_risk_percent"] == percent


def test_findrisc_maximum_is_26(engine):
    result = _findrisc_score(
        engine, age=65, bmi=31, waist_cm=103, physical_activity_mins_per_day=0,
        vegetables_daily=False, hypertension_medication=True,
        high_glucose_history=True, family_history_diabetes="first_degree",
    )
    assert result["score"] == 26
    assert result["risk_category"] == "Very High"
