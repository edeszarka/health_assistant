"""Service to orchestrate risk score calculations and persistence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import (
    UserProfile, LabResult, BloodPressureReading, 
    SamsungHealthMetric, RiskScore, FamilyHistory
)
from services.risk_engine import risk_engine


class RiskService:
    """Orchestrates fetching data and calculating risk scores."""

    async def calculate_and_save_all(self, db: AsyncSession) -> Dict[str, Any]:
        """Recalculate all scores based on latest data and save to DB."""
        # 1. Fetch User Profile
        result = await db.execute(select(UserProfile).limit(1))
        profile = result.scalar_one_or_none()
        if not profile:
            return {"error": "No user profile found"}

        # 2. Fetch latest Lab Results for Framingham
        tc_res = await db.execute(
            select(LabResult.value)
            .where(LabResult.test_name == "total_cholesterol")
            .order_by(LabResult.test_date.desc())
            .limit(1)
        )
        total_chol = tc_res.scalar_one_or_none()

        hdl_res = await db.execute(
            select(LabResult.value)
            .where(LabResult.test_name == "hdl_cholesterol")
            .order_by(LabResult.test_date.desc())
            .limit(1)
        )
        hdl_chol = hdl_res.scalar_one_or_none()

        glucose_res = await db.execute(
            select(LabResult.value)
            .where(LabResult.test_name == "glucose")
            .order_by(LabResult.test_date.desc())
            .limit(1)
        )
        latest_glucose = glucose_res.scalar_one_or_none()
        has_diabetes = (latest_glucose > 125) if latest_glucose else False

        # 3. Fetch latest BP for Framingham
        bp_res = await db.execute(
            select(BloodPressureReading)
            .order_by(BloodPressureReading.measured_at.desc())
            .limit(1)
        )
        latest_bp = bp_res.scalar_one_or_none()
        systolic = latest_bp.systolic if latest_bp else 120

        # 4. Fetch BMI for FINDRISC
        bmi_res = await db.execute(
            select(SamsungHealthMetric.value)
            .where(SamsungHealthMetric.metric_type == "bmi")
            .order_by(SamsungHealthMetric.recorded_at.desc())
            .limit(1)
        )
        bmi = bmi_res.scalar_one_or_none()

        # 5. Fetch Family History for FINDRISC
        fam_res = await db.execute(
            select(FamilyHistory)
            .where(FamilyHistory.condition.ilike("%diabetes%"))
            .limit(1)
        )
        fam_entry = fam_res.scalar_one_or_none()
        fam_diabetes = "none"
        if fam_entry:
            rel = fam_entry.relation.lower()
            if any(p in rel for p in ["mother", "father", "brother", "sister"]):
                fam_diabetes = "first_degree"
            else:
                fam_diabetes = "second_degree"

        results = {}

        # ─── Calculate Framingham ───────────────────────────────────────────
        if total_chol and hdl_chol:
            # Framingham expects mg/dL. 
            # If values are low (< 20), they are likely mmol/L (standard in Hungary).
            # Conversion: mmol/L * 38.67 = mg/dL
            tc_mgdl = total_chol * 38.67 if total_chol < 20 else total_chol
            hdl_mgdl = hdl_chol * 38.67 if hdl_chol < 20 else hdl_chol

            fram = risk_engine.calculate_framingham(
                age=profile.age,
                sex=profile.sex,
                total_cholesterol=tc_mgdl,
                hdl_cholesterol=hdl_mgdl,
                systolic_bp=systolic,
                bp_treated=profile.bp_medication,
                diabetes=has_diabetes,
                smoker=profile.smoking,
            )
            
            risk_row = RiskScore(
                score_type="framingham",
                score_value=fram["risk_percent"],
                risk_category=fram["risk_category"],
                inputs_json=json.dumps({
                    "age": profile.age,
                    "sex": profile.sex,
                    "tc": total_chol,
                    "hdl": hdl_chol,
                    "sbp": systolic,
                    "treated": profile.bp_medication,
                    "smoker": profile.smoking,
                    "diabetes": has_diabetes
                }),
                calculated_at=datetime.now(timezone.utc)
            )
            db.add(risk_row)
            results["framingham"] = fram

        # ─── Calculate FINDRISC ──────────────────────────────────────────────
        if bmi:
            findrisc = risk_engine.calculate_findrisc(
                age=profile.age,
                bmi=bmi,
                physical_activity_mins_per_day=30.0, # Default if unknown
                vegetables_daily=True,                # Default if unknown
                hypertension_medication=profile.bp_medication,
                high_glucose_history=has_diabetes,
                family_history_diabetes=fam_diabetes,
            )
            
            risk_row = RiskScore(
                score_type="findrisc",
                score_value=float(findrisc["score"]),
                risk_category=findrisc["risk_category"],
                inputs_json=json.dumps({
                    "age": profile.age,
                    "bmi": bmi,
                    "bp_med": profile.bp_medication,
                    "glucose_hist": has_diabetes,
                    "fam_diabetes": fam_diabetes
                }),
                calculated_at=datetime.now(timezone.utc)
            )
            db.add(risk_row)
            results["findrisc"] = findrisc

        await db.commit()
        return results


risk_service = RiskService()
