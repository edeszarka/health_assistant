"""Framingham and FINDRISC risk score calculators + AHA BP classification."""

from __future__ import annotations

from typing import Any


# AHA 2017 blood-pressure category cut-offs in mmHg.
# Source: Whelton et al., "2017 ACC/AHA Guideline for the Prevention, Detection,
# Evaluation, and Management of High Blood Pressure in Adults", Hypertension
# 2018;71:e13-e115. Each constant marks the lower bound of its category.
AHA_SYSTOLIC_ELEVATED = 120
AHA_DIASTOLIC_ELEVATED = 80
AHA_SYSTOLIC_STAGE_1 = 130
AHA_DIASTOLIC_STAGE_1 = 80
AHA_SYSTOLIC_STAGE_2 = 140
AHA_DIASTOLIC_STAGE_2 = 90
AHA_SYSTOLIC_CRISIS = 180
AHA_DIASTOLIC_CRISIS = 120


class RiskEngine:
    """Calculates cardiovascular, diabetes, and blood-pressure risk scores."""

    # ── Framingham ───────────────────────────────────────────────────────────
    # NCEP ATP III point score for men (Third Report, 2001; NHLBI "Estimate of
    # 10-Year Risk for CHD"). It estimates hard CHD for men aged 20-79. All
    # cholesterol values are in mg/dL. Diabetes is not a point item: ATP III
    # treats it as a CHD risk equivalent, so no score is given (see
    # framingham_unavailable_reason).

    _FRAMINGHAM_MIN_AGE = 20
    _FRAMINGHAM_MAX_AGE = 79

    _FRAMINGHAM_AGE = {
        (20, 34): -9,
        (35, 39): -4,
        (40, 44): 0,
        (45, 49): 3,
        (50, 54): 6,
        (55, 59): 8,
        (60, 64): 10,
        (65, 69): 11,
        (70, 74): 12,
        (75, 79): 13,
    }

    # Lower bounds of the total cholesterol bands after the first (<160).
    _FRAMINGHAM_TC_BANDS = (160, 200, 240, 280)
    # Points by age group, ordered: <160, 160-199, 200-239, 240-279, >=280.
    _FRAMINGHAM_TC = {
        (20, 39): (0, 4, 7, 9, 11),
        (40, 49): (0, 3, 5, 6, 8),
        (50, 59): (0, 2, 3, 4, 5),
        (60, 69): (0, 1, 1, 2, 3),
        (70, 79): (0, 0, 0, 1, 1),
    }

    # Points for a current smoker, by age group; a non-smoker gets 0.
    _FRAMINGHAM_SMOKER = {
        (20, 39): 8,
        (40, 49): 5,
        (50, 59): 3,
        (60, 69): 1,
        (70, 79): 1,
    }

    # HDL points as (lower bound, points), highest band first.
    _FRAMINGHAM_HDL = ((60, -1), (50, 0), (40, 1), (0, 2))

    _FRAMINGHAM_SBP_UNTREATED = {
        (0, 119): 0,
        (120, 129): 0,
        (130, 139): 1,
        (140, 159): 1,
        (160, 999): 2,
    }
    _FRAMINGHAM_SBP_TREATED = {
        (0, 119): 0,
        (120, 129): 1,
        (130, 139): 2,
        (140, 159): 2,
        (160, 999): 3,
    }

    # Points to 10-year risk %. The table's two open-ended rows are stored as
    # their nearest number: 0 points or fewer ("<1%") as 1, and 17 or more
    # ("30% or more") as 30, with a category that says so.
    _FRAMINGHAM_RISK = {
        1: 1, 2: 1, 3: 1, 4: 1, 5: 2, 6: 2, 7: 3, 8: 4, 9: 5, 10: 6,
        11: 8, 12: 10, 13: 12, 14: 16, 15: 20, 16: 25,
    }
    _FRAMINGHAM_RISK_FLOOR = 1.0
    _FRAMINGHAM_RISK_CEILING = 30.0
    _FRAMINGHAM_CEILING_POINTS = 17

    # Reasons shown or logged when a Framingham score is withheld.
    FRAMINGHAM_MEN_ONLY_REASON = "the Framingham table is implemented for men only"
    FRAMINGHAM_DIABETES_REASON = (
        "diagnosed diabetes counts as a coronary heart disease risk equivalent, "
        "so the Framingham table does not apply"
    )
    FRAMINGHAM_AGE_REASON = "the Framingham table covers ages 20-79"

    @classmethod
    def framingham_unavailable_reason(
        cls, sex: str | None, diabetes: bool, age: int | None
    ) -> str | None:
        """Return why no Framingham score may be given, or ``None`` if it may.

        Callers must not show or persist a Framingham score when this returns
        a reason. An unknown age is not a reason here: it is reported as a
        missing input.

        Args:
            sex: The profile's sex value, or ``None``.
            diabetes: Whether diabetes has been diagnosed.
            age: Age in years, or ``None`` when unknown.

        Returns:
            The reason as text, or ``None`` when the table applies.
        """
        if (sex or "").lower() != "male":
            return cls.FRAMINGHAM_MEN_ONLY_REASON
        if diabetes:
            return cls.FRAMINGHAM_DIABETES_REASON
        if age is not None and not cls._FRAMINGHAM_MIN_AGE <= age <= cls._FRAMINGHAM_MAX_AGE:
            return cls.FRAMINGHAM_AGE_REASON
        return None

    def calculate_framingham(
        self,
        age: int,
        sex: str,
        total_cholesterol: float,
        hdl_cholesterol: float,
        systolic_bp: int,
        bp_treated: bool,
        smoker: bool,
    ) -> dict:
        """Calculate 10-year CHD risk with the ATP III point score for men.

        Diabetes is not an input. Callers check diagnosed diabetes through
        ``framingham_unavailable_reason`` before calling this.

        Args:
            age: Patient age in years, 20-79.
            sex: The biological sex of the patient; only "male" is scored.
            total_cholesterol: Total cholesterol level in mg/dL (NOT mmol/L).
            hdl_cholesterol: High-density lipoprotein (HDL) cholesterol level in mg/dL (NOT mmol/L).
            systolic_bp: Systolic blood pressure reading in mmHg.
            bp_treated: True if the patient is on antihypertensive medication.
            smoker: True if the patient is a current smoker.

        Returns:
            Dict containing score_points, risk_percent, and risk_category.

        Raises:
            ValueError: If the table does not apply to this sex or age, or a
                cholesterol value is below the physiological floor for mg/dL,
                which usually means it was passed in as mmol/L.
        """
        reason = self.framingham_unavailable_reason(sex, False, age)
        if reason:
            raise ValueError(f"No Framingham score: {reason}.")
        # Non-physiological in mg/dL; a value this low most likely means the
        # caller supplied mmol/L. Refuse rather than produce a wrong score.
        if total_cholesterol < 50:
            raise ValueError(
                f"total_cholesterol={total_cholesterol} looks like mmol/L, "
                "expected mg/dL; convert the value before scoring."
            )
        if hdl_cholesterol < 10:
            raise ValueError(
                f"hdl_cholesterol={hdl_cholesterol} looks like mmol/L, "
                "expected mg/dL; convert the value before scoring."
            )

        sbp_table = self._FRAMINGHAM_SBP_TREATED if bp_treated else self._FRAMINGHAM_SBP_UNTREATED
        points = (
            self._lookup_range(self._FRAMINGHAM_AGE, age)
            + self._framingham_tc_points(age, total_cholesterol)
            + self._framingham_hdl_points(hdl_cholesterol)
            + self._lookup_range(sbp_table, systolic_bp)
            + (self._lookup_range(self._FRAMINGHAM_SMOKER, age) if smoker else 0)
        )
        risk_percent, category = self._framingham_risk(points)
        return {
            "score_points": points,
            "risk_percent": risk_percent,
            "risk_category": category,
        }

    def _framingham_tc_points(self, age: int, total_cholesterol: float) -> int:
        """Return the total cholesterol points for this age group."""
        band = sum(total_cholesterol >= bound for bound in self._FRAMINGHAM_TC_BANDS)
        return self._lookup_range(self._FRAMINGHAM_TC, age)[band]

    def _framingham_hdl_points(self, hdl_cholesterol: float) -> int:
        """Return the HDL points."""
        return next(
            points for bound, points in self._FRAMINGHAM_HDL if hdl_cholesterol >= bound
        )

    def _framingham_risk(self, points: int) -> tuple[float, str]:
        """Convert total points to ``(10-year risk %, category)``."""
        if points >= self._FRAMINGHAM_CEILING_POINTS:
            return self._FRAMINGHAM_RISK_CEILING, "High (30% or more)"
        risk = float(self._FRAMINGHAM_RISK.get(points, self._FRAMINGHAM_RISK_FLOOR))
        if risk < 10:
            return risk, "Low (<10%)"
        if risk <= 20:
            return risk, "Moderate (10-20%)"
        return risk, "High (>20%)"

    # ── FINDRISC ─────────────────────────────────────────────────────────────
    # Source: Lindström J, Tuomilehto J. The Diabetes Risk Score. Diabetes Care
    # 2003;26(3):725-731. https://doi.org/10.2337/diacare.26.3.725

    def calculate_findrisc(
        self,
        age: int,
        sex: str,
        waist_cm: float | None,
        bmi: float | None,
        physical_activity_mins_per_day: float,
        vegetables_daily: bool,
        hypertension_medication: bool,
        high_glucose_history: bool,
        family_history_diabetes: str = "none",
    ) -> dict:
        """Calculate FINDRISC type-2 diabetes risk score.

        Args:
            age: Patient age in years.
            sex: "male" or "female".
            waist_cm: Waist circumference in cm (optional).
            bmi: Body mass index (optional).
            physical_activity_mins_per_day: Average daily physical activity minutes.
            vegetables_daily: Whether the patient eats vegetables/fruit daily.
            hypertension_medication: Whether patient takes antihypertensive drugs.
            high_glucose_history: History of high blood glucose.
            family_history_diabetes: "none", "second_degree", or "first_degree".

        Returns:
            Dict with score, risk_category, ten_year_risk_percent, recommendation.
        """
        score = 0

        # 1. Age
        if age < 45: score += 0
        elif age < 55: score += 2
        elif age < 65: score += 3
        else: score += 4

        # 2. BMI
        if bmi is not None:
            if bmi < 25: score += 0
            elif bmi <= 30: score += 1
            else: score += 3
        
        # 3. Waist circumference
        if waist_cm is not None:
            if sex.lower() == "male":
                if waist_cm < 94: score += 0
                elif waist_cm <= 102: score += 3
                else: score += 4
            else:
                if waist_cm < 80: score += 0
                elif waist_cm <= 88: score += 3
                else: score += 4

        # 4. Lifestyle & Medical History
        if physical_activity_mins_per_day < 21: score += 2 # < 150 min/week
        if not vegetables_daily: score += 1
        if hypertension_medication: score += 2
        if high_glucose_history: score += 5

        # 5. Family history
        if family_history_diabetes == "first_degree": score += 5
        elif family_history_diabetes == "second_degree": score += 3

        # 6. Risk category mapping
        if score < 7:
            category, risk_pct, rec = "Low", 1.0, "Maintain healthy lifestyle."
        elif score < 12:
            category, risk_pct, rec = "Slightly elevated", 4.0, "Focus on diet and physical activity."
        elif score < 15:
            category, risk_pct, rec = "Moderate", 17.0, "Consult your GP for fasting glucose or HbA1c test."
        elif score <= 20:
            category, risk_pct, rec = "High", 33.0, "Refer to endocrinologist; lifestyle intervention recommended."
        else:
            category, risk_pct, rec = "Very High", 50.0, "Urgent referral to endocrinologist; high probability of existing diabetes."

        return {
            "score": score,
            "risk_category": category,
            "ten_year_risk_percent": risk_pct,
            "recommendation": rec,
        }

    # ── AHA BP Classification ─────────────────────────────────────────────────

    def classify_blood_pressure(self, systolic: int, diastolic: int) -> dict:
        """Classify blood pressure per AHA 2017 guidelines.

        Categories are evaluated most-severe-first so that a single severely
        elevated component cannot be masked by the other being normal.

        Note:
            The AHA chart wording is "higher than 180/120", but this
            implementation treats exactly 180/120 as crisis (``>=``),
            deliberately erring toward urgency in a health context.

        Args:
            systolic: Systolic pressure in mmHg.
            diastolic: Diastolic pressure in mmHg.

        Returns:
            Dict with category, action, and optional specialist.
        """
        if systolic >= AHA_SYSTOLIC_CRISIS or diastolic >= AHA_DIASTOLIC_CRISIS:
            return {
                "category": "Hypertensive Crisis",
                "action": "Seek immediate medical attention.",
                "specialist": "Emergency Medicine",
            }
        elif systolic >= AHA_SYSTOLIC_STAGE_2 or diastolic >= AHA_DIASTOLIC_STAGE_2:
            return {
                "category": "Stage 2 Hypertension",
                "action": "Medication likely needed; see your doctor soon.",
                "specialist": "Cardiologist",
            }
        elif systolic >= AHA_SYSTOLIC_STAGE_1 or diastolic >= AHA_DIASTOLIC_STAGE_1:
            return {
                "category": "Stage 1 Hypertension",
                "action": "Lifestyle changes; consider medication.",
                "specialist": "GP",
            }
        elif (
            systolic >= AHA_SYSTOLIC_ELEVATED
            and diastolic < AHA_DIASTOLIC_ELEVATED
        ):
            return {
                "category": "Elevated",
                "action": "Lifestyle changes recommended.",
                "specialist": "GP",
            }
        else:
            return {
                "category": "Normal",
                "action": "Maintain healthy lifestyle.",
                "specialist": None,
            }

    # ── Utilities ────────────────────────────────────────────────────────────

    @staticmethod
    def _lookup_range(table: dict, value: int) -> Any:
        """Return the table value whose (lo, hi) key range contains value.

        Raises:
            ValueError: If no range contains the value.
        """
        for (lo, hi), pts in table.items():
            if lo <= value <= hi:
                return pts
        raise ValueError(f"{value} is outside the table's range.")


risk_engine = RiskEngine()
