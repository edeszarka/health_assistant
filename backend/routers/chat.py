"""Chat router: RAG-augmented LLM conversation with direct DB data injection."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import ChatRequest, ChatResponse
from models.db_models import (
    UserProfile,
    SamsungHealthMetric,
    LabResult,
    BloodPressureReading,
    FamilyHistory,
    RiskScore,
)
from services.rag_service import rag_service
from services.llm_service import llm_service
from services.risk_engine import risk_engine

router = APIRouter()


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def _detect_language(message: str) -> str:
    """
    Detect whether the user is writing in Hungarian or English.
    Returns 'Hungarian' or 'English'.
    """
    hungarian_chars = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")
    hungarian_words = {
        "és", "hogy", "nem", "van", "egy", "az", "de", "mi", "ez",
        "mit", "kérem", "szeretnék", "tudod", "tudom", "igen", "nincs",
        "milyen", "miért", "hogyan", "mennyi", "mikor", "hol",
    }
    has_hu_chars = any(c in hungarian_chars for c in message)
    has_hu_words = any(w in message.lower().split() for w in hungarian_words)
    return "Hungarian" if (has_hu_chars or has_hu_words) else "English"


# ---------------------------------------------------------------------------
# Context builders
# Each function owns exactly one data domain. No overlap with rag_service.
# ---------------------------------------------------------------------------

async def _build_health_metrics_summary(db: AsyncSession) -> str:
    """
    YOUR activity and biometric numbers from Samsung Health and Zepp.
    Covers last 7 days detail, 30-day averages, 18-month top days,
    monthly step averages, HR, sleep, weight, calories.
    """
    lines = []
    today   = date.today()
    last_7  = today - timedelta(days=7)
    last_30 = today - timedelta(days=30)
    last_18m = today - timedelta(days=548)

    try:
        # Steps — last 7 days
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "steps")
            .where(SamsungHealthMetric.recorded_at >= last_7)
            .order_by(SamsungHealthMetric.recorded_at.desc())
        )
        step_rows = result.scalars().all()
        if step_rows:
            lines.append("=== Steps (last 7 days) ===")
            for row in step_rows:
                d = row.recorded_at.date() if hasattr(row.recorded_at, "date") else row.recorded_at
                lines.append(f"  {d}: {int(row.value):,} steps")
            avg_7 = sum(r.value for r in step_rows) / len(step_rows)
            lines.append(f"  7-day average: {int(avg_7):,} steps/day")

        # Steps — 30-day average and peak
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "steps")
            .where(SamsungHealthMetric.recorded_at >= last_30)
        )
        step_30 = result.scalars().all()
        if step_30:
            avg_30  = sum(r.value for r in step_30) / len(step_30)
            max_day = max(step_30, key=lambda r: r.value)
            max_date = max_day.recorded_at.date() if hasattr(max_day.recorded_at, "date") else max_day.recorded_at
            lines.append(f"  30-day average: {int(avg_30):,} steps/day")
            lines.append(f"  30-day peak: {int(max_day.value):,} steps (on {max_date})")

        # Steps — top 10 days in 18 months
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "steps")
            .where(SamsungHealthMetric.recorded_at >= last_18m)
            .order_by(SamsungHealthMetric.value.desc())
            .limit(10)
        )
        top_rows = result.scalars().all()
        if top_rows:
            lines.append("\n=== Top 10 Step Days (last 18 months) ===")
            for row in top_rows:
                d = row.recorded_at.date() if hasattr(row.recorded_at, "date") else row.recorded_at
                lines.append(f"  {d}: {int(row.value):,} steps")

        # Steps — monthly averages 18 months
        month_col = func.date_trunc("month", SamsungHealthMetric.recorded_at)
        result = await db.execute(
            select(
                month_col.label("month"),
                func.avg(SamsungHealthMetric.value).label("avg_steps"),
                func.max(SamsungHealthMetric.value).label("max_steps"),
                func.count(SamsungHealthMetric.value).label("day_count"),
            )
            .where(SamsungHealthMetric.metric_type == "steps")
            .where(SamsungHealthMetric.recorded_at >= last_18m)
            .group_by(month_col)
            .order_by(month_col)
        )
        monthly_rows = result.all()
        if monthly_rows:
            lines.append("\n=== Monthly Step Averages (last 18 months) ===")
            for row in monthly_rows:
                month_str = row.month.strftime("%Y-%m") if hasattr(row.month, "strftime") else str(row.month)[:7]
                lines.append(
                    f"  {month_str}: {int(row.avg_steps):,} avg/day "
                    f"(best: {int(row.max_steps):,}, {row.day_count} days)"
                )

        # Resting HR — last 30 days
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "resting_hr")
            .where(SamsungHealthMetric.recorded_at >= last_30)
            .order_by(SamsungHealthMetric.recorded_at.desc())
        )
        hr_rows = result.scalars().all()
        if hr_rows:
            avg_hr = sum(r.value for r in hr_rows) / len(hr_rows)
            latest_hr = hr_rows[0]
            d = latest_hr.recorded_at.date() if hasattr(latest_hr.recorded_at, "date") else latest_hr.recorded_at
            lines.append("\n=== Resting Heart Rate (last 30 days) ===")
            lines.append(f"  Latest: {int(latest_hr.value)} bpm (on {d})")
            lines.append(f"  30-day average: {avg_hr:.1f} bpm")

        # Sleep — last 7 days
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "sleep_total_min")
            .where(SamsungHealthMetric.recorded_at >= last_7)
            .order_by(SamsungHealthMetric.recorded_at.desc())
        )
        sleep_rows = result.scalars().all()
        if sleep_rows:
            lines.append("\n=== Sleep (last 7 days) ===")
            for row in sleep_rows:
                d = row.recorded_at.date() if hasattr(row.recorded_at, "date") else row.recorded_at
                lines.append(f"  {d}: {row.value / 60:.1f} hours")
            avg_sleep = sum(r.value for r in sleep_rows) / len(sleep_rows) / 60
            lines.append(f"  7-day average: {avg_sleep:.1f} hours/night")

        # Weight — latest only
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "weight_kg")
            .order_by(SamsungHealthMetric.recorded_at.desc())
            .limit(1)
        )
        weight = result.scalar_one_or_none()
        if weight:
            lines.append("\n=== Weight ===")
            lines.append(f"  Latest: {weight.value} kg")

        # Active calories — last 7 days
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "active_calories")
            .where(SamsungHealthMetric.recorded_at >= last_7)
        )
        cal_rows = result.scalars().all()
        if cal_rows:
            avg_cal = sum(r.value for r in cal_rows) / len(cal_rows)
            lines.append("\n=== Active Calories (last 7 days avg) ===")
            lines.append(f"  Average: {int(avg_cal)} kcal/day")

    except Exception as e:
        lines.append(f"(Error fetching Samsung metrics: {e})")

    return "\n".join(lines) if lines else "No Samsung Health / wearable data available."


async def _build_lab_trends_summary(db: AsyncSession) -> str:
    """
    YOUR lab history with trend analysis.
    Groups results by test name, computes direction and % change over time.
    Derives HIGH/LOW from ref_range columns (no flag_direction column in schema).
    """
    lines = []
    try:
        result = await db.execute(
            select(LabResult)
            .where(LabResult.test_date.isnot(None))
            .order_by(LabResult.test_name, LabResult.test_date)
        )
        all_labs = result.scalars().all()
        if not all_labs:
            return "No lab results on record."

        by_test: dict[str, list] = defaultdict(list)
        for r in all_labs:
            by_test[r.test_name].append(r)

        RISK_SCORE_LABS = {
            "total_cholesterol", "hdl_cholesterol", "ldl_cholesterol",
            "cholesterol", "hdl", "ldl", "glucose", "hba1c", "triglycerides",
        }
        RELEVANT_LAB_TESTS = {
            "wbc", "rbc", "hemoglobin", "hematocrit", "platelets",
            "lymphocytes_abs", "lymphocytes_pct", "monocytes_abs", "monocytes_pct",
            "neutrophils_abs", "neutrophils_pct", "eosinophils_abs", "eosinophils_pct",
            "basophils_abs", "basophils_pct", "mcv", "mch", "mchc", "mpv", "esr",
            "glucose", "hba1c", "bun", "creatinine", "uric_acid", "egfr",
            "sodium", "potassium", "calcium", "magnesium", "chloride",
            "ast", "alt", "ggt", "gamma_gt", "alp", "total_bilirubin", "direct_bilirubin",
            "total_cholesterol", "hdl_cholesterol", "ldl_cholesterol", "triglycerides",
            "serum_iron", "ferritin", "transferrin", "tibc", "total_protein", "albumin",
            "tsh", "free_t4", "free_t3", "crp", "urinalysis", "urine_sediment",
        }

        flagged_lines = []
        trend_lines   = []
        stable_lines  = []

        for test_name, readings in sorted(by_test.items()):
            if test_name not in RELEVANT_LAB_TESTS:
                continue

            readings    = sorted(readings, key=lambda r: r.test_date or date.min)
            values      = [r.value for r in readings if r.value is not None]
            dates       = [r.test_date for r in readings if r.value is not None]
            if not values:
                continue

            latest_row  = readings[-1]
            unit        = latest_row.unit or ""
            raw_name    = latest_row.raw_name
            latest_date = dates[-1]
            is_flagged  = latest_row.is_flagged or False

            # Derive HIGH/LOW from ref range (no flag_direction column)
            if is_flagged and latest_row.ref_range_high is not None:
                direction = "HIGH ↑" if latest_row.value > latest_row.ref_range_high else "LOW ↓"
            elif is_flagged and latest_row.ref_range_low is not None:
                direction = "LOW ↓" if latest_row.value < latest_row.ref_range_low else "HIGH ↑"
            else:
                direction = "OUT OF RANGE"

            # Trend calculation
            if len(values) == 1:
                history = f"{values[0]} {unit}"
                trend   = "single reading"
            else:
                history   = " → ".join(str(v) for v in values) + f" {unit}"
                first, last_val = values[0], values[-1]
                pct = (last_val - first) / abs(first) * 100 if first != 0 else 0
                if pct > 10:
                    trend = f"↑ rising +{pct:.0f}% over {len(values)} tests"
                elif pct < -10:
                    trend = f"↓ falling {abs(pct):.0f}% over {len(values)} tests"
                else:
                    trend = "→ stable"

            ref = ""
            if latest_row.ref_range_low is not None and latest_row.ref_range_high is not None:
                ref = f" (ref: {latest_row.ref_range_low}–{latest_row.ref_range_high} {unit})"

            line = (
                f"  {raw_name} ({test_name}): {history}{ref} "
                f"[{trend}] — latest {latest_date}"
            )

            if is_flagged:
                flagged_lines.append(f"  ⚠ {line} [{direction}]")
            elif test_name in RISK_SCORE_LABS or "rising" in trend:
                trend_lines.append(line)
            else:
                stable_lines.append(line)

        if flagged_lines:
            lines.append("=== Flagged lab values ===")
            lines.extend(flagged_lines)
        if trend_lines:
            lines.append("\n=== Key risk score values and notable trends ===")
            lines.extend(trend_lines)
        if stable_lines:
            lines.append("\n=== Stable lab values ===")
            lines.extend(stable_lines)

    except Exception as e:
        lines.append(f"(Error fetching lab trends: {e})")

    return "\n".join(lines) if lines else "No lab results on record."


async def _build_bp_summary(db: AsyncSession) -> str:
    """
    YOUR blood pressure history.
    Always returns latest reading regardless of age, plus average if 3+ readings.
    """
    try:
        result = await db.execute(
            select(BloodPressureReading)
            .order_by(BloodPressureReading.measured_at.desc())
            .limit(30)
        )
        readings = result.scalars().all()
        if not readings:
            return "No blood pressure readings recorded."

        latest = readings[0]
        lines  = [
            "=== Blood pressure ===",
            f"  Latest: {latest.systolic}/{latest.diastolic} mmHg, "
            f"pulse {latest.pulse} bpm ({latest.measured_at.date()})",
        ]
        if len(readings) >= 3:
            avg_sys = sum(r.systolic for r in readings) / len(readings)
            avg_dia = sum(r.diastolic for r in readings) / len(readings)
            lines.append(
                f"  Average over {len(readings)} readings: "
                f"{avg_sys:.0f}/{avg_dia:.0f} mmHg"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"(Error fetching BP data: {e})"


async def _build_family_history_summary(db: AsyncSession) -> str:
    """YOUR family risk factors."""
    try:
        result  = await db.execute(select(FamilyHistory))
        entries = result.scalars().all()
        if not entries:
            return "No family history recorded."
        lines = [
            f"  {e.relation}: {e.condition}"
            + (f" (onset age {e.age_of_onset})" if e.age_of_onset else "")
            for e in entries
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"(Error fetching family history: {e})"


async def _build_risk_scores(
    db: AsyncSession,
    profile: UserProfile | None,
    user_message: str = "",
) -> dict:
    """
    Calculate FINDRISC from profile, fetch Framingham from RiskScore table,
    and detect hypothetical values in the user's message to re-run either
    score with overrides. All math is done in Python — the LLM only presents results.
    """
    scores = {}
    fam_diabetes = "none" 
    # ── Helper: fetch latest lab value ───────────────────────────────────────
    async def _get_lab(test_name: str) -> float | None:
        res = await db.execute(
            select(LabResult.value)
            .where(LabResult.test_name == test_name)
            .where(LabResult.test_date.isnot(None))
            .order_by(LabResult.test_date.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        return float(row) if row is not None else None

    async def _get_latest_systolic() -> int | None:
        res = await db.execute(
            select(BloodPressureReading.systolic)
            .order_by(BloodPressureReading.measured_at.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        return int(row) if row is not None else None

    async def _get_latest_weight() -> float | None:
        res = await db.execute(
            select(SamsungHealthMetric.value)
            .where(SamsungHealthMetric.metric_type == "weight_kg")
            .order_by(SamsungHealthMetric.recorded_at.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        return float(row) if row is not None else None

    try:
        weight_kg  = await _get_latest_weight()
        bmi_from_db = None
        if weight_kg and profile and profile.height_cm:
            bmi_from_db = weight_kg / ((profile.height_cm / 100) ** 2)

        # ── 1. Base FINDRISC from profile ─────────────────────────────────────
        if profile:
            fam_diabetes = "first_degree" if getattr(profile, "family_diabetes", False) else "none"
            findrisc = risk_engine.calculate_findrisc(
                age=profile.age,
                sex=profile.sex,
                waist_cm=getattr(profile, "waist_cm", None),
                bmi=bmi_from_db,
                physical_activity_mins_per_day=30.0,
                vegetables_daily=getattr(profile, "vegetables_daily", False),
                hypertension_medication=getattr(profile, "bp_medication", False),
                high_glucose_history=getattr(profile, "high_glucose_history", False),
                family_history_diabetes=fam_diabetes,
            )
            scores["findrisc_score"] = findrisc["score"]
            scores["findrisc_category"] = findrisc["risk_category"]

        # ── 2. Base Framingham from RiskScore table ───────────────────────────
        res = await db.execute(
            select(RiskScore)
            .where(RiskScore.score_type == "framingham")
            .order_by(RiskScore.calculated_at.desc())
            .limit(1)
        )
        rs_fram = res.scalar_one_or_none()
        if rs_fram:
            scores["framingham_risk_percent"] = rs_fram.score_value

        # ── 3. Detect hypothetical inputs in user message ─────────────────────
        msg = user_message.lower()

        # --- FINDRISC hypothetical ---
        findrisc_overrides: dict = {}
        findrisc_labels: list[str] = []

        m = re.search(r"waist\s*(?:circumference)?[^\d]*(\d+\.?\d*)\s*cm", msg)
        if m:
            findrisc_overrides["waist_cm"] = float(m.group(1))
            findrisc_labels.append(f"waist_cm={m.group(1)} cm")

        m = re.search(r"(\d+\.?\d*)\s*kg", msg)
        if m and profile and profile.height_cm:
            hypo_weight = float(m.group(1))
            findrisc_overrides["bmi"] = hypo_weight / ((profile.height_cm / 100) ** 2)
            findrisc_labels.append(f"weight={m.group(1)} kg")

        m = re.search(r"\bbmi\b\D*(\d+\.?\d*)", msg)
        if m:
            findrisc_overrides["bmi"] = float(m.group(1))
            findrisc_labels.append(f"BMI={m.group(1)}")

        if findrisc_overrides and profile:
            h = risk_engine.calculate_findrisc(
                age=profile.age,
                sex=profile.sex,
                waist_cm=findrisc_overrides.get("waist_cm", getattr(profile, "waist_cm", None)),
                bmi=findrisc_overrides.get("bmi", bmi_from_db),
                physical_activity_mins_per_day=30.0,
                vegetables_daily=getattr(profile, "vegetables_daily", False),
                hypertension_medication=getattr(profile, "bp_medication", False),
                high_glucose_history=getattr(profile, "high_glucose_history", False),
                family_history_diabetes=fam_diabetes,
            )
            scores["findrisc_hypothetical"] = (
                f"Score={h['score']} ({h['risk_category']}, "
                f"10-yr risk {h['ten_year_risk_percent']}%) "
                f"— recalculated with {', '.join(findrisc_labels)}"
            )

        # --- Framingham hypothetical ---
        fram_overrides: dict = {}
        fram_labels: list[str] = []

        m = re.search(r"(?:total\s+)?cholesterol[^\d]*(\d+\.?\d*)", msg)
        if m:
            fram_overrides["total_cholesterol"] = float(m.group(1))
            fram_labels.append(f"total_cholesterol={m.group(1)}")

        m = re.search(r"\bhdl\b[^\d]*(\d+\.?\d*)", msg)
        if m:
            fram_overrides["hdl_cholesterol"] = float(m.group(1))
            fram_labels.append(f"HDL={m.group(1)}")

        m = re.search(r"systolic[^\d]*(\d+)|blood pressure[^\d]*(\d+)", msg)
        if m:
            val = m.group(1) or m.group(2)
            fram_overrides["systolic_bp"] = int(val)
            fram_labels.append(f"systolic_bp={val}")

        if fram_labels and profile:
            tc    = fram_overrides.get("total_cholesterol") or await _get_lab("total_cholesterol") or await _get_lab("cholesterol")
            hdl   = fram_overrides.get("hdl_cholesterol")  or await _get_lab("hdl_cholesterol")  or await _get_lab("hdl")
            sys_bp = fram_overrides.get("systolic_bp")     or await _get_latest_systolic()

            if tc and hdl and sys_bp:
                g = risk_engine.calculate_framingham(
                    age=profile.age,
                    sex=profile.sex,
                    total_cholesterol=tc,
                    hdl_cholesterol=hdl,
                    systolic_bp=sys_bp,
                    bp_treated=getattr(profile, "bp_medication", False),
                    diabetes=getattr(profile, "high_glucose_history", False),
                    smoker=getattr(profile, "smoking", False),
                )
                scores["framingham_hypothetical"] = (
                    f"{g['risk_percent']}% 10-yr CV risk ({g['risk_category']}) "
                    f"— recalculated with {', '.join(fram_labels)}"
                )
            else:
                missing = []
                if not tc:   missing.append("total cholesterol")
                if not hdl:  missing.append("HDL cholesterol")
                if not sys_bp: missing.append("systolic BP")
                scores["framingham_hypothetical"] = (
                    f"Cannot recalculate: missing {', '.join(missing)} from database."
                )

    except Exception as e:
        print(f"Error calculating risk scores: {e}")
    return scores




# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    Accept a user message, build full context from DB, return LLM reply.

    Architecture:
    - chat.py   → structured data (SQL): labs, metrics, BP, family history
    - rag_service → unstructured knowledge (vector search): medical context
    - llm_service → receives both, reasons over them, never fetches data itself
    """
    # Detect language first — passed to LLM to enforce reply language
    user_language = _detect_language(request.message)

    # User profile
    try:
        result  = await db.execute(select(UserProfile).limit(1))
        profile = result.scalar_one_or_none()
    except Exception:
        profile = None

    # Structured context — direct SQL, one domain per function
    metrics_summary = await _build_health_metrics_summary(db)
    lab_summary     = await _build_lab_trends_summary(db)
    bp_summary      = await _build_bp_summary(db)
    family_summary  = await _build_family_history_summary(db)
    risk_scores     = await _build_risk_scores(db, profile, request.message)

    # RAG — semantic search for medical knowledge only, no structured data
    try:
        rag_context = await rag_service.build_context(request.message, profile, db)
    except Exception:
        rag_context = ""

    # LLM — receives everything, decides nothing about data fetching
    try:
        reply = await llm_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
            context=rag_context,
            user_profile=profile,
            risk_scores=risk_scores,
            query_type=getattr(request, "query_type", "general"),
            user_language=user_language,
            health_metrics_summary=metrics_summary,
            flagged_values=lab_summary,
            bp_summary=bp_summary,
            family_history_summary=family_summary,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    return ChatResponse(reply=reply, sources=[])
