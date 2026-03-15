"""Chat router: RAG-augmented LLM conversation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, desc

from database.connection import get_db
from models.api_models import ChatRequest, ChatResponse
from models.db_models import UserProfile, SamsungHealthMetric
from services.rag_service import rag_service
from services.llm_service import llm_service

router = APIRouter()

async def _build_health_metrics_summary(db: AsyncSession) -> str:
    """Build a comprehensive 18-month summary of health metrics."""
    today = datetime.now(timezone.utc)
    last_18m = today - timedelta(days=548)
    last_30d = today - timedelta(days=30)
    last_7d = today - timedelta(days=7)

    sections = []

    # Steps - last 7 days detailed
    stmt_7d = (
        select(SamsungHealthMetric)
        .where(SamsungHealthMetric.metric_type == "steps", SamsungHealthMetric.recorded_at >= last_7d)
        .order_by(desc(SamsungHealthMetric.recorded_at))
    )
    res_7d = await db.execute(stmt_7d)
    steps_7d = res_7d.scalars().all()
    if steps_7d:
        sections.append("=== Steps (Last 7 Days) ===")
        for s in steps_7d:
            sections.append(f"  {s.recorded_at.strftime('%Y-%m-%d')}: {int(s.value):,} steps")
            
    # Steps - 30-day average
    stmt_30d_avg = (
        select(func.avg(SamsungHealthMetric.value))
        .where(SamsungHealthMetric.metric_type == "steps", SamsungHealthMetric.recorded_at >= last_30d)
    )
    res_30d_avg = await db.execute(stmt_30d_avg)
    avg_30d = res_30d_avg.scalar()
    if avg_30d:
        sections.append(f"\n=== Steps (30-day Average) ===\n  {int(avg_30d):,} steps/day")

    # Steps - top 10 days in last 18 months
    stmt_top_10 = (
        select(SamsungHealthMetric)
        .where(SamsungHealthMetric.metric_type == "steps", SamsungHealthMetric.recorded_at >= last_18m)
        .order_by(desc(SamsungHealthMetric.value))
        .limit(10)
    )
    res_top_10 = await db.execute(stmt_top_10)
    top_10 = res_top_10.scalars().all()
    if top_10:
        sections.append("\n=== Top 10 Step Days (Last 18 months) ===")
        for s in top_10:
            sections.append(f"  {s.recorded_at.strftime('%Y-%m-%d')}: {int(s.value):,} steps")

    # Steps - monthly averages for last 18 months
    stmt_monthly = (
        select(
            func.date_trunc('month', SamsungHealthMetric.recorded_at).label('month'),
            func.avg(SamsungHealthMetric.value).label('avg_steps'),
            func.count(SamsungHealthMetric.value).label('day_count')
        )
        .where(SamsungHealthMetric.metric_type == "steps", SamsungHealthMetric.recorded_at >= last_18m)
        .group_by(func.date_trunc('month', SamsungHealthMetric.recorded_at))
        .order_by(func.date_trunc('month', SamsungHealthMetric.recorded_at))
    )
    res_monthly = await db.execute(stmt_monthly)
    monthly_data = res_monthly.all()
    if monthly_data:
        sections.append("\n=== Monthly Step Averages (last 18 months) ===")
        for row in monthly_data:
            if row.month and row.avg_steps is not None:
                month_str = row.month.strftime("%Y-%m")
                sections.append(f"  {month_str}: {int(row.avg_steps):,} avg steps/day ({row.day_count} days)")

    # Weight - latest entry (no change to window)
    stmt_weight = (
        select(SamsungHealthMetric)
        .where(SamsungHealthMetric.metric_type == "weight_kg")
        .order_by(desc(SamsungHealthMetric.recorded_at))
        .limit(1)
    )
    weight = (await db.execute(stmt_weight)).scalar_one_or_none()
    if weight:
        sections.append(f"\n=== Current Weight ===\n  {weight.value:.1f} kg (on {weight.recorded_at.strftime('%Y-%m-%d')})")
        
    # Resting HR: 18 months window (latest, 30d avg, overall avg)
    stmt_hr = (
        select(SamsungHealthMetric)
        .where(SamsungHealthMetric.metric_type == "resting_heart_rate", SamsungHealthMetric.recorded_at >= last_18m)
        .order_by(desc(SamsungHealthMetric.recorded_at))
    )
    hr_latest = (await db.execute(stmt_hr.limit(1))).scalar_one_or_none()
    if hr_latest:
        hr_30d_avg = (await db.execute(select(func.avg(SamsungHealthMetric.value)).where(SamsungHealthMetric.metric_type == "resting_heart_rate", SamsungHealthMetric.recorded_at >= last_30d))).scalar() or 0
        hr_all_avg = (await db.execute(select(func.avg(SamsungHealthMetric.value)).where(SamsungHealthMetric.metric_type == "resting_heart_rate", SamsungHealthMetric.recorded_at >= last_18m))).scalar() or 0
        sections.append(f"\n=== Resting Heart Rate (Last 18 months) ===")
        sections.append(f"  Latest: {int(hr_latest.value)} bpm (on {hr_latest.recorded_at.strftime('%Y-%m-%d')})")
        sections.append(f"  30-day Avg: {int(hr_30d_avg)} bpm")
        sections.append(f"  18-month Avg: {int(hr_all_avg)} bpm")

    # Sleep - 30 days window for avg
    stmt_sleep_30d = (
        select(func.avg(SamsungHealthMetric.value))
        .where(SamsungHealthMetric.metric_type == "sleep", SamsungHealthMetric.recorded_at >= last_30d)
    )
    sleep_avg = (await db.execute(stmt_sleep_30d)).scalar()
    if sleep_avg:
        sections.append(f"\n=== Sleep (30-day Average) ===\n  {sleep_avg:.1f} mins/night")

    # Active calories - 30 days window for avg
    stmt_cal_30d = (
        select(func.avg(SamsungHealthMetric.value))
        .where(SamsungHealthMetric.metric_type == "active_calories", SamsungHealthMetric.recorded_at >= last_30d)
    )
    cal_avg = (await db.execute(stmt_cal_30d)).scalar()
    if cal_avg:
        sections.append(f"\n=== Active Calories (30-day Average) ===\n  {int(cal_avg):,} kcal/day")

    return "\n".join(sections)



@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Accept a user message, build RAG context, return LLM reply.

    Args:
        request: ChatRequest with message and conversation history.
        db: Async DB session.

    Returns:
        ChatResponse with reply and source list.
    """
    # Fetch user profile (first row, if exists)
    try:
        result = await db.execute(select(UserProfile).limit(1))
        profile = result.scalar_one_or_none()
    except Exception:
        profile = None

    # Build RAG context
    try:
        context = await rag_service.build_context(request.message, profile, db)
        health_summary = await _build_health_metrics_summary(db)
        if health_summary:
            context += f"\n\n{health_summary}"
    except Exception as exc:
        context = ""

    # Call LLM
    try:
        reply = await llm_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
            context=context,
            user_profile=profile,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    return ChatResponse(reply=reply, sources=[])
