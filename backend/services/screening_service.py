"""Preventive screening recommendations using USPSTF guidelines."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.api_models import ScreeningRecommendation
from services.medlineplus_service import medlineplus_service


# Rules: (condition, min_age, max_age, sex_filter, family_history_trigger, urgency, specialist)
SCREENING_RULES: list[tuple] = [
    ("Blood pressure screening", 18, 999, None, None, "routine", "GP"),
    ("Diabetes screening (HbA1c)", 35, 70, None, None, "routine", "GP"),
    ("Diabetes screening (HbA1c)", 25, 34, None, ["diabetes"], "routine", "Endocrinologist"),
    ("Lipid panel", 20, 999, None, ["cardiovascular disease", "heart attack"], "routine", "Cardiologist"),
    ("Colorectal cancer screening", 45, 75, None, None, "routine", "Gastroenterologist"),
    ("Cervical cancer screening (Pap smear)", 21, 65, "female", None, "routine", "Gynecologist"),
    ("Breast cancer screening (mammogram)", 40, 74, "female", None, "routine", "Radiologist"),
    ("Abdominal aortic aneurysm ultrasound", 65, 75, "male", None, "routine", "Vascular Surgeon"),
    ("Thyroid function (TSH)", 35, 999, "female", None, "routine", "Endocrinologist"),
    ("Osteoporosis screening (DEXA)", 65, 999, "female", None, "routine", "Rheumatologist"),
    ("Lung cancer screening (low-dose CT)", 50, 80, None, None, "routine", "Pulmonologist"),
]


class ScreeningService:
    """Generates personalised preventive screening recommendations."""

    def __init__(self) -> None:
        self._guidelines: list[dict] = []
        self._load_guidelines()

    def _load_guidelines(self) -> None:
        """Load USPSTF guidelines JSON at startup."""
        guideline_path = Path(__file__).parents[2] / "data_sample" / "uspstf_guidelines.json"
        try:
            with open(guideline_path, "r", encoding="utf-8") as f:
                self._guidelines = json.load(f)
        except Exception:
            self._guidelines = []

    async def get_recommendations(
        self,
        age: int,
        sex: str,
        family_history_conditions: list[str],
        flagged_lab_keys: list[str],
        framingham_score: Optional[float],
        findrisc_score: Optional[int],
        db: AsyncSession,
    ) -> list[ScreeningRecommendation]:
        """Generate personalised recommendations.

        Args:
            age: Patient age.
            sex: "male" / "female" / "other".
            family_history_conditions: List of condition strings from family history.
            flagged_lab_keys: List of normalised lab test keys that are out of range.
            framingham_score: Framingham 10-year risk % (or None if not calculated).
            findrisc_score: FINDRISC total score (or None if not calculated).
            db: Async DB session (for MedlinePlus lookups).

        Returns:
            Sorted list of ScreeningRecommendation (urgent first).
        """
        recs: list[ScreeningRecommendation] = []
        seen: set[str] = set()
        fam_lower = [c.lower() for c in family_history_conditions]

        for (condition, min_age, max_age, sex_filter, fam_trigger, urgency, specialist) in SCREENING_RULES:
            # Age filter
            if not (min_age <= age <= max_age):
                continue
            # Sex filter
            if sex_filter and sex.lower() != sex_filter:
                continue
            # Family history trigger
            if fam_trigger:
                if not any(
                    trigger.lower() in cond for trigger in fam_trigger for cond in fam_lower
                ):
                    continue

            if condition in seen:
                continue
            seen.add(condition)

            # Enrich with MedlinePlus
            try:
                ml_info = await medlineplus_service.search_health_topic(condition, db)
            except Exception:
                ml_info = {"url": None, "summary": ""}

            recs.append(
                ScreeningRecommendation(
                    test_name=condition,
                    reason=self._build_reason(condition, age, sex, fam_lower),
                    urgency=urgency,
                    specialist=specialist,
                    medlineplus_url=ml_info.get("url"),
                    medlineplus_summary=ml_info.get("summary"),
                )
            )

        # Dynamic recommendations based on risk scores
        if framingham_score is not None and framingham_score > 10:
            if "Cardiology consultation" not in seen:
                seen.add("Cardiology consultation")
                recs.append(
                    ScreeningRecommendation(
                        test_name="Cardiology consultation",
                        reason=f"Framingham 10-year cardiovascular risk is {framingham_score:.1f}%.",
                        urgency="soon",
                        specialist="Cardiologist",
                    )
                )

        if findrisc_score is not None and findrisc_score >= 12:
            if "Diabetes risk evaluation" not in seen:
                seen.add("Diabetes risk evaluation")
                recs.append(
                    ScreeningRecommendation(
                        test_name="Diabetes risk evaluation",
                        reason=f"FINDRISC score is {findrisc_score} (moderate-high risk).",
                        urgency="soon",
                        specialist="Endocrinologist",
                    )
                )

        # Sort: urgent → soon → routine
        urgency_order = {"urgent": 0, "soon": 1, "routine": 2}
        recs.sort(key=lambda r: urgency_order.get(r.urgency, 9))
        return recs

    @staticmethod
    def _build_reason(condition: str, age: int, sex: str, fam_conditions: list[str]) -> str:
        """Compose a human-readable reason string."""
        fam_str = (
            f" Family history includes: {', '.join(fam_conditions[:3])}."
            if fam_conditions
            else ""
        )
        return (
            f"USPSTF recommends {condition} for {sex}s aged {age}.{fam_str} "
            "Please consult your doctor to confirm."
        )


screening_service = ScreeningService()
