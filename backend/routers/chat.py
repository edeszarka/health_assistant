"""Chat router: RAG-augmented LLM conversation with direct DB data injection."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import ChatRequest, ChatResponse
from models.db_models import (
    UserProfile, SamsungHealthMetric, LabResult,
    BloodPressureReading, FamilyHistory, RiskScore,
)
from services.rag_service import rag_service
from services.llm_service import llm_service
from services.risk_engine import risk_engine

router = APIRouter()


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def _detect_language(message: str) -> str:
    """Detect whether the user is writing in Hungarian or English."""
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
# Intent detection
# ---------------------------------------------------------------------------

def _detect_intent(message: str) -> dict:
    """Detect which data domains are relevant to the user's query.

    Keyword-based — no LLM call needed. Used to skip irrelevant DB fetches
    and keep the system prompt token count low.
    """
    msg = message.lower()
    domains = set()

    if any(w in msg for w in ["lépés", "steps", "walk", "aktivit", "kalória",
                               "calorie", "sleep", "alvás", "hr", "pulzus", "szív"]):
        domains.add("activity")
    if any(w in msg for w in ["labor", "vérkép", "koleszterin", "lab", "blood",
                               "glucose", "hba1c", "ferritin", "tsh", "ldl", "hdl"]):
        domains.add("labs")
    if any(w in msg for w in ["vérnyomás", "blood pressure", "bp", "szisztolés", "diastolic"]):
        domains.add("bp")
    if any(w in msg for w in ["család", "family", "history", "előzmény"]):
        domains.add("family")
    if not domains:
        # General question — load everything
        domains = {"activity", "labs", "bp", "family"}

    return {"domains": domains}


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

async def _build_health_metrics_summary(db: AsyncSession) -> str:
    """Query samsung_health_metrics and return a plain-text summary."""
    lines = []
    today = date.today()
    last_7  = today - timedelta(days=7)
    last_30 = today - timedelta(days=30)

    try:
        # Steps: last 7 days
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

        # Steps: last 30 days
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "steps")
            .where(SamsungHealthMetric.recorded_at >= last_30)
        )
        step_30 = result.scalars().all()
        if step_30:
            avg_30 = sum(r.value for r in step_30) / len(step_30)
            max_day = max(step_30, key=lambda r: r.value)
            max_date = max_day.recorded_at.date() if hasattr(max_day.recorded_at, "date") else max_day.recorded_at
            lines.append(f"  30-day average: {int(avg_30):,} steps/day")
            lines.append(f"  30-day maximum: {int(max_day.value):,} steps (on {max_date})")

        # Steps: top 10 days in last 18 months
        last_18m = today - timedelta(days=548)
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

        # Steps: monthly averages for last 18 months
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
                    f"  {month_str}: {int(row.avg_steps):,} avg steps/day "
                    f"(best day: {int(row.max_steps):,}, data from {row.day_count} days)"
                )

        # Resting heart rate: last 30 days
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

        # Sleep: last 7 days
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

        # Weight: latest only
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "weight_kg")
            .order_by(SamsungHealthMetric.recorded_at.desc())
            .limit(1)
        )
        weight = result.scalar_one_or_none()
        if weight:
            lines.append(f"\n=== Weight ===")
            lines.append(f"  Latest: {weight.value} kg")

        # Active calories: last 7 days
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "active_calories")
            .where(SamsungHealthMetric.recorded_at >= last_7)
        )
        cal_rows = result.scalars().all()
        if cal_rows:
            avg_cal = sum(r.value for r in cal_rows) / len(cal_rows)
            lines.append(f"\n=== Active Calories (last 7 days avg) ===")
            lines.append(f"  Average: {int(avg_cal)} kcal/day")

    except Exception as e:
        lines.append(f"(Error fetching Samsung metrics: {e})")

    return "\n".join(lines) if lines else "No Samsung Health data available."


async def _build_lab_flags_summary(db: AsyncSession) -> str:
    """Fetch recent out-of-range lab results.

    Note: LabResult has no flag_direction column — direction is derived
    by comparing value against ref_range_low / ref_range_high.
    """
    try:
        result = await db.execute(
            select(LabResult)
            .where(LabResult.is_flagged == True)
            .order_by(LabResult.test_date.desc())
            .limit(10)
        )
        flagged = result.scalars().all()
        if not flagged:
            return "No flagged lab values on record."

        lines = []
        for r in flagged:
            # Derive direction from reference range — no flag_direction column in model
            if r.ref_range_high is not None and r.value > r.ref_range_high:
                direction = "HIGH ↑"
            elif r.ref_range_low is not None and r.value < r.ref_range_low:
                direction = "LOW ↓"
            else:
                direction = "OUT OF RANGE"

            ref_str = (
                f"{r.ref_range_low}–{r.ref_range_high}"
                if r.ref_range_low is not None and r.ref_range_high is not None
                else "N/A"
            )
            lines.append(
                f"  {r.test_date}: {r.raw_name} = {r.value} {r.unit or ''} "
                f"(ref: {ref_str}) [{direction}]"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"(Error fetching lab flags: {e})"


async def _build_bp_summary(db: AsyncSession) -> str:
    """Fetch 30-day blood pressure average and latest reading."""
    try:
        last_30 = date.today() - timedelta(days=30)
        result = await db.execute(
            select(BloodPressureReading)
            .where(BloodPressureReading.measured_at >= last_30)
            .order_by(BloodPressureReading.measured_at.desc())
        )
        readings = result.scalars().all()
        if not readings:
            return "No blood pressure readings in last 30 days."

        avg_sys   = sum(r.systolic  for r in readings) / len(readings)
        avg_dia   = sum(r.diastolic for r in readings) / len(readings)
        # pulse may be None
        pulse_vals = [r.pulse for r in readings if r.pulse is not None]
        avg_pulse_str = f", pulse {sum(pulse_vals)/len(pulse_vals):.0f} bpm" if pulse_vals else ""
        latest = readings[0]
        pulse_str = f", pulse {latest.pulse} bpm" if latest.pulse else ""
        return (
            f"Latest: {latest.systolic}/{latest.diastolic} mmHg{pulse_str} "
            f"({latest.measured_at.date()})\n"
            f"30-day average: {avg_sys:.0f}/{avg_dia:.0f} mmHg{avg_pulse_str} "
            f"({len(readings)} readings)"
        )
    except Exception as e:
        return f"(Error fetching BP data: {e})"


async def _build_family_history_summary(db: AsyncSession) -> str:
    """Fetch all family history entries."""
    try:
        result = await db.execute(select(FamilyHistory))
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
    profile: Optional[UserProfile],
    user_message: str = "",
) -> Dict[str, Any]:
    """Fetch stored Framingham and calculate FINDRISC risk scores."""
    scores: Dict[str, Any] = {}
    try:
        # FINDRISC — calculated from profile fields
        if profile:
            weight_result = await db.execute(
                select(SamsungHealthMetric.value)
                .where(SamsungHealthMetric.metric_type == "weight_kg")
                .order_by(SamsungHealthMetric.recorded_at.desc())
                .limit(1)
            )
            weight_kg = weight_result.scalar_one_or_none()
            bmi = None
            if weight_kg and profile.height_cm:
                bmi = float(weight_kg) / ((profile.height_cm / 100) ** 2)

            fam_diabetes = "first_degree" if getattr(profile, "family_diabetes", False) else "none"
            findrisc = risk_engine.calculate_findrisc(
                age=profile.age,
                sex=profile.sex,
                waist_cm=getattr(profile, "waist_cm", None),
                bmi=bmi,
                physical_activity_mins_per_day=30.0,
                vegetables_daily=getattr(profile, "vegetables_daily", False),
                hypertension_medication=getattr(profile, "bp_medication", False),
                high_glucose_history=getattr(profile, "high_glucose_history", False),
                family_history_diabetes=fam_diabetes,
            )
            scores["findrisc_score"] = findrisc["score"]
            scores["findrisc_category"] = findrisc["risk_category"]

        # Framingham — read latest stored value from risk_scores table
        fram_result = await db.execute(
            select(RiskScore)
            .where(RiskScore.score_type == "framingham")
            .order_by(RiskScore.calculated_at.desc())
            .limit(1)
        )
        rs_fram = fram_result.scalar_one_or_none()
        if rs_fram:
            scores["framingham_risk_percent"] = rs_fram.score_value

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
    """Accept a user message, build full context from DB, return LLM reply.

    Architecture:
    - chat.py    → structured data (SQL): labs, metrics, BP, family history
    - rag_service → unstructured knowledge (vector search): medical context
    - llm_service → receives both, reasons over them, never fetches data itself

    Args:
        request: The ChatRequest containing message and history.
        db: Async database session.

    Returns:
        A ChatResponse object containing the assistant's reply.
    """
    # 1. Detect which data domains the question is about.
    intent  = _detect_intent(request.message)
    domains = intent["domains"]

    # 2. Fetch user profile (always needed — small query)
    try:
        result  = await db.execute(select(UserProfile).limit(1))
        profile = result.scalar_one_or_none()
    except Exception:
        profile = None

    # 3. Build only the context sections relevant to this query.
    metrics_summary = (
        await _build_health_metrics_summary(db)
        if "activity" in domains else ""
    )
    lab_summary = (
        await _build_lab_flags_summary(db)
        if "labs" in domains else ""
    )
    bp_summary = (
        await _build_bp_summary(db)
        if "bp" in domains else ""
    )
    family_summary = (
        await _build_family_history_summary(db)
        if "family" in domains else ""
    )

    # 4. Risk scores — only when relevant
    query_type = getattr(request, "query_type", "general")
    risk_scores: Dict[str, Any] = {}
    if "labs" in domains or "bp" in domains or query_type == "risk_analysis":
        risk_scores = await _build_risk_scores(db, profile, request.message)

    # 5. RAG — skip for pure activity questions (vector store has guidelines, not steps)
    rag_context = ""
    if domains & {"labs", "bp", "family"}:
        try:
            rag_context = await rag_service.build_context(request.message, profile, db)
        except Exception as exc:
            rag_context = f"(Medical knowledge retrieval unavailable: {exc})"

    # 6. Detect language
    user_language = _detect_language(request.message)

    # 7. Call LLM
    try:
        reply = await llm_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
            context=rag_context,
            user_profile=profile,
            risk_scores=risk_scores,
            query_type=query_type,
            user_language=user_language,
            health_metrics_summary=metrics_summary,
            flagged_values=lab_summary,
            bp_summary=bp_summary,
            family_history_summary=family_summary,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    return ChatResponse(reply=reply, sources=[])