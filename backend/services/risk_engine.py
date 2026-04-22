"""Framingham and FINDRISC risk score calculators + AHA BP classification."""

from __future__ import annotations


class RiskEngine:
    """Calculates cardiovascular, diabetes, and blood-pressure risk scores."""

    # ── Framingham (Wilson et al. 1998) ──────────────────────────────────────

    # Point tables: age points by sex
    _FRAMINGHAM_AGE_MALE = {
        (20, 34): -9,
        (35, 39): -4,
        (40, 44): 0,
        (45, 49): 3,
        (50, 54): 6,
        (55, 59): 8,
        (60, 64): 10,
        (65, 69): 11,
        (70, 74): 12,
        (75, 999): 13,
    }
    _FRAMINGHAM_AGE_FEMALE = {
        (20, 34): -7,
        (35, 39): -3,
        (40, 44): 0,
        (45, 49): 3,
        (50, 54): 6,
        (55, 59): 8,
        (60, 64): 10,
        (65, 69): 12,
        (70, 74): 14,
        (75, 999): 16,
    }

    # Total cholesterol by age group (points for <160, 160-199, 200-239, 240-279, ≥280)
    _FRAMINGHAM_TC_MALE = {
        (20, 39): [0, 4, 7, 9, 11],
        (40, 49): [0, 3, 5, 6, 8],
        (50, 59): [0, 2, 3, 4, 5],
        (60, 69): [0, 1, 1, 2, 3],
        (70, 999): [0, 0, 0, 1, 1],
    }
    _FRAMINGHAM_TC_FEMALE = {
        (20, 39): [0, 4, 8, 11, 13],
        (40, 49): [0, 3, 6, 8, 10],
        (50, 59): [0, 2, 4, 5, 7],
        (60, 69): [0, 1, 2, 3, 4],
        (70, 999): [0, 1, 1, 2, 2],
    }

    # HDL points (≥60, 50-59, 40-49, <40)
    _FRAMINGHAM_HDL = [(-1), 0, 1, 2]

    # SBP points (treated vs untreated) for male/female
    _FRAMINGHAM_SBP_MALE_UNTREATED = {
        (0, 119): 0,
        (120, 129): 0,
        (130, 139): 1,
        (140, 159): 1,
        (160, 999): 2,
    }
    _FRAMINGHAM_SBP_MALE_TREATED = {
        (0, 119): 0,
        (120, 129): 1,
        (130, 139): 2,
        (140, 159): 2,
        (160, 999): 3,
    }
    _FRAMINGHAM_SBP_FEMALE_UNTREATED = {
        (0, 119): 0,
        (120, 129): 1,
        (130, 139): 2,
        (140, 159): 3,
        (160, 999): 4,
    }
    _FRAMINGHAM_SBP_FEMALE_TREATED = {
        (0, 119): 0,
        (120, 129): 3,
        (130, 139): 4,
        (140, 159): 5,
        (160, 999): 6,
    }

    # 10-year risk lookup tables (points → risk %)
    _FRAMINGHAM_RISK_MALE = {
        -3: 1,
        -2: 1,
        -1: 1,
        0: 1,
        1: 1,
        2: 1,
        3: 1,
        4: 1,
        5: 2,
        6: 2,
        7: 3,
        8: 4,
        9: 5,
        10: 6,
        11: 8,
        12: 10,
        13: 12,
        14: 16,
        15: 20,
        16: 25,
    }
    _FRAMINGHAM_RISK_FEMALE = {
        -3: 1,
        -2: 1,
        -1: 1,
        0: 1,
        1: 1,
        2: 1,
        3: 1,
        4: 1,
        5: 2,
        6: 2,
        7: 3,
        8: 4,
        9: 5,
        10: 6,
        11: 8,
        12: 10,
        13: 12,
        14: 16,
        15: 20,
        16: 25,
    }

    def calculate_framingham(
        self,
        age: int,
        sex: str,
        total_cholesterol: float,
        hdl_cholesterol: float,
        systolic_bp: int,
        bp_treated: bool,
        diabetes: bool,
        smoker: bool,
    ) -> dict:
        """Calculate 10-year cardiovascular risk using Framingham Point Score.

        Args:
            age: Patient age in years.
            sex: The biological sex of the patient ("male" or "female").
            total_cholesterol: Total cholesterol level in mg/dL.
            hdl_cholesterol: High-density lipoprotein (HDL) cholesterol level in mg/dL.
            systolic_bp: Systolic blood pressure reading in mmHg.
            bp_treated: True if the patient is on antihypertensive medication, False otherwise.
            diabetes: True if the patient has a diagnosis of diabetes, False otherwise.
            smoker: True if the patient is a current smoker, False otherwise.

        Returns:
            A dictionary containing:
                - score_points (int): The total calculated Framingham points.
                - risk_percent (float): The estimated 10-year risk of a cardiovascular event.
                - risk_category (str): A qualitative description of the risk level (e.g., "Low", "High").
        """
        male = sex.lower() == "male"
        points = 0

        # Age points
        age_table = self._FRAMINGHAM_AGE_MALE if male else self._FRAMINGHAM_AGE_FEMALE
        points += self._lookup_range(age_table, age)

        # Total cholesterol points
        tc_table = self._FRAMINGHAM_TC_MALE if male else self._FRAMINGHAM_TC_FEMALE
        tc_pts_list = self._lookup_range(tc_table, age)
        if isinstance(tc_pts_list, list):
            tc_idx = (
                0
                if total_cholesterol < 160
                else (
                    1
                    if total_cholesterol < 200
                    else (
                        2
                        if total_cholesterol < 240
                        else 3 if total_cholesterol < 280 else 4
                    )
                )
            )
            points += tc_pts_list[tc_idx]

        # HDL points
        hdl_idx = (
            0
            if hdl_cholesterol >= 60
            else 1 if hdl_cholesterol >= 50 else 2 if hdl_cholesterol >= 40 else 3
        )
        points += self._FRAMINGHAM_HDL[hdl_idx]

        # SBP points
        if male:
            sbp_table = (
                self._FRAMINGHAM_SBP_MALE_TREATED
                if bp_treated
                else self._FRAMINGHAM_SBP_MALE_UNTREATED
            )
        else:
            sbp_table = (
                self._FRAMINGHAM_SBP_FEMALE_TREATED
                if bp_treated
                else self._FRAMINGHAM_SBP_FEMALE_UNTREATED
            )
        points += self._lookup_range(sbp_table, systolic_bp)

        # Smoking
        if smoker:
            points += 8 if male else 9

        # Diabetes
        if diabetes:
            points += 11 if male else 13

        # Clamp to lookup range
        risk_table = (
            self._FRAMINGHAM_RISK_MALE if male else self._FRAMINGHAM_RISK_FEMALE
        )
        clamped = max(min(points, max(risk_table.keys())), min(risk_table.keys()))
        risk_pct = risk_table.get(clamped, 30)

        category = (
            "Low (<10%)"
            if risk_pct < 10
            else "Moderate (10-20%)" if risk_pct <= 20 else "High (>20%)"
        )
        return {
            "score_points": points,
            "risk_percent": float(risk_pct),
            "risk_category": category,
        }

    # ── FINDRISC ─────────────────────────────────────────────────────────────

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
        # "none" / "second_degree" / "first_degree"
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

        # Age
        if age < 45:
            score += 0
        elif age < 55:
            score += 2
        elif age < 65:
            score += 3
        else:
            score += 4

        # BMI
        if bmi is not None:
            if bmi < 25:
                score += 0
            elif bmi <= 30:
                score += 1
            else:
                score += 3
        
        # Waist circumference
        if waist_cm is not None:
            if sex.lower() == "male":
                if waist_cm < 94:
                    score += 0
                elif 94 <= waist_cm <= 102:
                    score += 3
                else:
                    score += 4
            else:
                if waist_cm < 80:
                    score += 0
                elif 80 <= waist_cm <= 88:
                    score += 3
                else:
                    score += 4

        # Physical activity (≥30 min/day most days → ≥30 * 5/7)
        if physical_activity_mins_per_day < 21:  # ~30min × 5/7 days
            score += 2

        # Vegetables
        if not vegetables_daily:
            score += 1

        # BP medication
        if hypertension_medication:
            score += 2

        # High glucose history
        if high_glucose_history:
            score += 5

        # Family history
        if family_history_diabetes == "first_degree":
            score += 5
        elif family_history_diabetes == "second_degree":
            score += 3

        # Risk category + 10-year risk
        if score < 7:
            category = "Low"
            risk_pct = 1.0
            rec = "Maintain healthy lifestyle."
        elif score < 12:
            category = "Slightly elevated"
            risk_pct = 4.0
            rec = "Focus on diet and physical activity."
        elif score < 15:
            category = "Moderate"
            risk_pct = 17.0
            rec = "Consult your GP for fasting glucose or HbA1c test."
        elif score < 20:
            category = "High"
            risk_pct = 33.0
            rec = "Refer to endocrinologist; lifestyle intervention recommended."
        else:
            category = "Very High"
            risk_pct = 50.0
            rec = "Urgent referral to endocrinologist; high probability of existing diabetes."

        return {
            "score": score,
            "risk_category": category,
            "ten_year_risk_percent": risk_pct,
            "recommendation": rec,
        }

    # ── AHA BP Classification ─────────────────────────────────────────────────

    def classify_blood_pressure(self, systolic: int, diastolic: int) -> dict:
        """Classify blood pressure per AHA 2017 guidelines.

        Args:
            systolic: Systolic pressure in mmHg.
            diastolic: Diastolic pressure in mmHg.

        Returns:
            Dict with category, action, and optional specialist.
        """
        if systolic < 120 and diastolic < 80:
            return {
                "category": "Normal",
                "action": "Maintain healthy lifestyle.",
                "specialist": None,
            }
        elif systolic < 130 and diastolic < 80:
            return {
                "category": "Elevated",
                "action": "Lifestyle changes recommended.",
                "specialist": "GP",
            }
        elif systolic < 140 or diastolic < 90:
            return {
                "category": "Stage 1 Hypertension",
                "action": "Lifestyle changes; consider medication.",
                "specialist": "GP",
            }
        elif systolic < 180 or diastolic < 120:
            return {
                "category": "Stage 2 Hypertension",
                "action": "Medication likely needed; see your doctor soon.",
                "specialist": "Cardiologist",
            }
        else:
            return {
                "category": "Hypertensive Crisis",
                "action": "Seek immediate medical attention.",
                "specialist": "Emergency Medicine",
            }

    # ── Utilities ────────────────────────────────────────────────────────────

    @staticmethod
    def _lookup_range(table: dict, value: int | float) -> int | list:
        """Return the table value whose (lo, hi) key range contains value."""
        for (lo, hi), pts in table.items():
            if lo <= value <= hi:
                return pts
        # Return last entry for out-of-range high values
        return list(table.values())[-1]


risk_engine = RiskEngine()
