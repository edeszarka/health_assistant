"""Preventive screening recommendations using USPSTF guidelines."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from models.api_models import ScreeningRecommendation
from services.medlineplus_service import medlineplus_service

logger = logging.getLogger(__name__)


@dataclass
class ScreeningRule:
    """Represents a preventive screening guideline rule.
    
    Attributes:
        condition: The name of the medical screening or test.
        min_age: Minimum age for the recommendation.
        max_age: Maximum age for the recommendation.
        sex_filter: If set, rule only applies to this sex ("male"/"female").
        family_trigger: List of condition keywords that trigger this rule if found in family history.
        urgency: Level of urgency ("routine", "soon", "urgent").
        specialist: The type of medical specialist recommended.
    """
    condition: str
    min_age: int
    max_age: int
    sex_filter: Optional[str] = None
    family_trigger: Optional[List[str]] = None
    urgency: str = "routine"
    specialist: str = "GP"


# Rules: based on USPSTF A/B recommendations
SCREENING_RULES: List[ScreeningRule] = [
    ScreeningRule("Blood pressure screening", 18, 999),
    ScreeningRule("Diabetes screening (HbA1c)", 35, 70),
    ScreeningRule(
        "Diabetes screening (HbA1c)",
        25,
        34,
        family_trigger=["diabetes"],
        specialist="Endocrinologist",
    ),
    ScreeningRule(
        "Lipid panel",
        20,
        999,
        family_trigger=["cardiovascular disease", "heart attack"],
        specialist="Cardiologist",
    ),
    ScreeningRule(
        "Colorectal cancer screening",
        45,
        75,
        specialist="Gastroenterologist",
    ),
    ScreeningRule(
        "Cervical cancer screening (Pap smear)",
        21,
        65,
        sex_filter="female",
        specialist="Gynecologist",
    ),
    ScreeningRule(
        "Breast cancer screening (mammogram)",
        40,
        74,
        sex_filter="female",
        specialist="Radiologist",
    ),
    ScreeningRule(
        "Abdominal aortic aneurysm ultrasound",
        65,
        75,
        sex_filter="male",
        specialist="Vascular Surgeon",
    ),
    ScreeningRule(
        "Thyroid function (TSH)",
        35,
        999,
        sex_filter="female",
        specialist="Endocrinologist",
    ),
    ScreeningRule(
        "Osteoporosis screening (DEXA)",
        65,
        999,
        sex_filter="female",
        specialist="Rheumatologist",
    ),
    ScreeningRule(
        "Lung cancer screening (low-dose CT)",
        50,
        80,
        specialist="Pulmonologist",
    ),
]


class ScreeningService:
    """Generates personalised preventive screening recommendations."""

    def __init__(self) -> None:
        self._guidelines: list[dict] = []
        self._load_guidelines()

    def _load_guidelines(self) -> None:
        """Load USPSTF guidelines JSON at startup."""
        guideline_path = (
            Path(__file__).parents[2] / "data_sample" / "uspstf_guidelines.json"
        )
        try:
            with open(guideline_path, "r", encoding="utf-8") as f:
                self._guidelines = json.load(f)
        except Exception as exc:
            logger.error(f"Failed to load screening guidelines: {exc}")
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
        seen_conditions: set[str] = set()
        fam_lower = [c.lower() for c in family_history_conditions]

        for rule in SCREENING_RULES:
            # Age filter
            if not (rule.min_age <= age <= rule.max_age):
                continue
            # Sex filter
            if rule.sex_filter and sex.lower() != rule.sex_filter:
                continue
            # Family history trigger
            if rule.family_trigger:
                if not any(
                    trigger.lower() in cond
                    for trigger in rule.family_trigger
                    for cond in fam_lower
                ):
                    continue

            if rule.condition in seen_conditions:
                continue
            seen_conditions.add(rule.condition)

            # Enrich with MedlinePlus
            try:
                ml_info = await medlineplus_service.search_health_topic(rule.condition, db)
            except Exception as exc:
                logger.warning(f"MedlinePlus lookup failed for {rule.condition}: {exc}")
                ml_info = {"url": None, "summary": ""}

            recs.append(
                ScreeningRecommendation(
                    test_name=rule.condition,
                    reason=self._build_reason(rule.condition, age, sex, fam_lower),
                    urgency=rule.urgency,
                    specialist=rule.specialist,
                    medlineplus_url=ml_info.get("url"),
                    medlineplus_summary=ml_info.get("summary"),
                )
            )

        # Dynamic recommendations based on risk scores
        if framingham_score is not None and framingham_score > 10:
            if "Cardiology consultation" not in seen_conditions:
                seen_conditions.add("Cardiology consultation")
                recs.append(
                    ScreeningRecommendation(
                        test_name="Cardiology consultation",
                        reason=f"Framingham 10-year cardiovascular risk is {framingham_score:.1f}%.",
                        urgency="soon",
                        specialist="Cardiologist",
                    )
                )

        if findrisc_score is not None and findrisc_score >= 12:
            if "Diabetes risk evaluation" not in seen_conditions:
                seen_conditions.add("Diabetes risk evaluation")
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
    def _build_reason(
        condition: str, age: int, sex: str, fam_conditions: list[str]
    ) -> str:
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
