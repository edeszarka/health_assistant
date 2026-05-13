"""Chat router: RAG-augmented LLM conversation with direct DB data injection."""
from __future__ import annotations

import json
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
    """Query samsung_health_metrics and return a VERY brief plain-text summary."""
    lines = []
    today = date.today()
    last_3  = today - timedelta(days=3)

    try:
        # Steps: last 3 days only
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "steps")
            .where(SamsungHealthMetric.recorded_at >= last_3)
            .order_by(SamsungHealthMetric.recorded_at.desc())
        )
        step_rows = result.scalars().all()
        if step_rows:
            lines.append("=== Recent Steps ===")
            for row in step_rows:
                d = row.recorded_at.date() if hasattr(row.recorded_at, "date") else row.recorded_at
                lines.append(f"  {d}: {int(row.value):,} steps")

        # Resting heart rate: latest only
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "resting_hr")
            .order_by(SamsungHealthMetric.recorded_at.desc())
            .limit(1)
        )
        latest_hr = result.scalar_one_or_none()
        if latest_hr:
            d = latest_hr.recorded_at.date() if hasattr(latest_hr.recorded_at, "date") else latest_hr.recorded_at
            lines.append(f"\nLatest HR: {int(latest_hr.value)} bpm ({d})")

        # Weight: latest only
        result = await db.execute(
            select(SamsungHealthMetric)
            .where(SamsungHealthMetric.metric_type == "weight_kg")
            .order_by(SamsungHealthMetric.recorded_at.desc())
            .limit(1)
        )
        weight = result.scalar_one_or_none()
        if weight:
            lines.append(f"Latest Weight: {weight.value} kg")

    except Exception as e:
        lines.append(f"(Error: {e})")

    return "\n".join(lines) if lines else "No recent wearable data."


async def _build_lab_flags_summary(db: AsyncSession) -> str:
    """Fetch only the 3 most recent out-of-range lab results."""
    try:
        result = await db.execute(
            select(LabResult)
            .where(LabResult.is_flagged == True)
            .order_by(LabResult.test_date.desc())
            .limit(3)
        )
        flagged = result.scalars().all()
        if not flagged:
            return "No flagged lab values."

        lines = []
        for r in flagged:
            lines.append(f"  {r.test_date}: {r.raw_name} {r.value} {r.unit or ''} (Flagged)")
        return "\n".join(lines)
    except Exception as e:
        return f"(Error: {e})"


async def _build_bp_summary(db: AsyncSession) -> str:
    """Fetch ONLY latest blood pressure reading."""
    try:
        result = await db.execute(
            select(BloodPressureReading)
            .order_by(BloodPressureReading.measured_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if not latest:
            return "No BP data."
        return f"Latest BP: {latest.systolic}/{latest.diastolic} mmHg ({latest.measured_at.date()})"
    except Exception as e:
        return f"(Error: {e})"


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


from services.risk_service import risk_service

async def _build_risk_scores(
    db: AsyncSession,
) -> Dict[str, Any]:
    """Recalculate and return the latest Framingham and FINDRISC scores."""
    try:
        results = await risk_service.calculate_and_save_all(db)
        scores = {}
        if "framingham" in results:
            scores["framingham_risk_percent"] = results["framingham"]["risk_percent"]
        if "findrisc" in results:
            scores["findrisc_score"] = results["findrisc"]["score"]
        return scores
    except Exception as e:
        print(f"Error calculating risk scores in chat: {e}")
        return {}


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Accept a user message, build full context from DB, return LLM reply.

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
        risk_scores = await _build_risk_scores(db)

    # 5. RAG — skip for pure activity questions (vector store has guidelines, not steps)
    rag_context = ""
    if domains & {"labs", "bp", "family"}:
        try:
            rag_context = await rag_service.build_context(request.message, profile, db)
        except Exception as exc:
            rag_context = f"(Medical knowledge retrieval unavailable: {exc})"

    # 6. Call LLM
    try:
        reply = await llm_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
            context=rag_context,
            user_profile=profile,
            risk_scores=risk_scores,
            query_type=query_type,
            health_metrics_summary=metrics_summary,
            flagged_values=lab_summary,
            bp_summary=bp_summary,
            family_history_summary=family_summary,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    return ChatResponse(reply=reply, sources=[])
