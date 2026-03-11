"""Chat router: RAG-augmented LLM conversation with direct DB data injection."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import ChatRequest, ChatResponse
from models.db_models import UserProfile, SamsungHealthMetric, LabResult, BloodPressureReading, FamilyHistory
from services.rag_service import rag_service
from services.llm_service import llm_service

router = APIRouter()


async def _build_health_metrics_summary(db: AsyncSession) -> str:
    """
    Directly query samsung_health_metrics and return a plain-text summary
    that gets injected verbatim into the LLM system prompt.
    Covers last 30 days + last 7 days highlight.
    """
    lines = []
    today = date.today()
    last_7  = today - timedelta(days=7)
    last_30 = today - timedelta(days=30)

    try:
        # --- Steps: last 7 days ---
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
                d = row.recorded_at.date() if hasattr(row.recorded_at, 'date') else row.recorded_at
                lines.append(f"  {d}: {int(row.value):,} steps")
            avg_7 = sum(r.value for r in step_rows) / len(step_rows)
            lines.append(f"  7-day average: {int(avg_7):,} steps/day")

        # --- Steps: last 30 days average ---
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "steps")
            .where(SamsungHealthMetric.recorded_at >= last_30)
        )
        step_30 = result.scalars().all()
        if step_30:
            avg_30 = sum(r.value for r in step_30) / len(step_30)
            max_30 = max(r.value for r in step_30)
            max_day = max(step_30, key=lambda r: r.value)
            max_date = max_day.recorded_at.date() if hasattr(max_day.recorded_at, 'date') else max_day.recorded_at
            lines.append(f"  30-day average: {int(avg_30):,} steps/day")
            lines.append(f"  30-day maximum: {int(max_30):,} steps (on {max_date})")

        # --- Resting heart rate: last 30 days ---
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "resting_hr")
            .where(SamsungHealthMetric.recorded_at >= last_30)
            .order_by(SamsungHealthMetric.recorded_at.desc())
        )
        hr_rows = result.scalars().all()
        if hr_rows:
            lines.append("\n=== Resting Heart Rate (last 30 days) ===")
            avg_hr = sum(r.value for r in hr_rows) / len(hr_rows)
            latest_hr = hr_rows[0]
            latest_hr_date = latest_hr.recorded_at.date() if hasattr(latest_hr.recorded_at, 'date') else latest_hr.recorded_at
            lines.append(f"  Latest: {int(latest_hr.value)} bpm (on {latest_hr_date})")
            lines.append(f"  30-day average: {avg_hr:.1f} bpm")

        # --- Sleep: last 7 days ---
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
                d = row.recorded_at.date() if hasattr(row.recorded_at, 'date') else row.recorded_at
                hours = row.value / 60
                lines.append(f"  {d}: {hours:.1f} hours")
            avg_sleep = sum(r.value for r in sleep_rows) / len(sleep_rows) / 60
            lines.append(f"  7-day average: {avg_sleep:.1f} hours/night")

        # --- Weight: latest entry ---
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

        # --- Active calories: last 7 days ---
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

    if not lines:
        return "No Samsung Health data available."

    return "\n".join(lines)


async def _build_lab_flags_summary(db: AsyncSession) -> str:
    """Fetch recent out-of-range lab results."""
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
            direction = "HIGH ↑" if r.flag_direction == "high" else "LOW ↓"
            lines.append(
                f"  {r.test_date}: {r.raw_name} = {r.value} {r.unit} "
                f"(ref: {r.ref_range_low}–{r.ref_range_high}) [{direction}]"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"(Error fetching lab flags: {e})"


async def _build_bp_summary(db: AsyncSession) -> str:
    """Fetch 30-day blood pressure average."""
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
        avg_sys = sum(r.systolic for r in readings) / len(readings)
        avg_dia = sum(r.diastolic for r in readings) / len(readings)
        avg_pulse = sum(r.pulse for r in readings) / len(readings)
        latest = readings[0]
        return (
            f"Latest: {latest.systolic}/{latest.diastolic} mmHg, pulse {latest.pulse} bpm\n"
            f"30-day average: {avg_sys:.0f}/{avg_dia:.0f} mmHg, pulse {avg_pulse:.0f} bpm "
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
        lines = [f"  {e.relation}: {e.condition}" +
                 (f" (onset age {e.age_of_onset})" if e.age_of_onset else "")
                 for e in entries]
        return "\n".join(lines)
    except Exception as e:
        return f"(Error fetching family history: {e})"


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Accept a user message, build full context from DB, return LLM reply."""

    # 1. Fetch user profile
    try:
        result = await db.execute(select(UserProfile).limit(1))
        profile = result.scalar_one_or_none()
    except Exception:
        profile = None

    # 2. Build all context sections directly from DB
    metrics_summary   = await _build_health_metrics_summary(db)
    lab_flags_summary = await _build_lab_flags_summary(db)
    bp_summary        = await _build_bp_summary(db)
    family_summary    = await _build_family_history_summary(db)

    # 3. RAG similarity search for additional context
    try:
        rag_context = await rag_service.build_context(request.message, profile, db)
    except Exception:
        rag_context = ""

    # 4. Call LLM with all context filled in
    try:
        reply = await llm_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
            context=rag_context,
            user_profile=profile,
            query_type=getattr(request, "query_type", "general"),
            health_metrics_summary=metrics_summary,
            flagged_values=lab_flags_summary,
            bp_summary=bp_summary,
            family_history_summary=family_summary,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    return ChatResponse(reply=reply, sources=[])
