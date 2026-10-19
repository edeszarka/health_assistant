"""Tests for the explicit risk request: stored inputs, no LLM, form request."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from models.api_models import ChatRequest, ProfileData, RiskInputsStatus, StoredInput
from routers import chat as chat_router
from routers.chat import _detect_intent, _is_risk_calculation_request, chat
from services.risk_inputs_text import format_risk_inputs


def _empty_status() -> RiskInputsStatus:
    return RiskInputsStatus(
        weight_kg=StoredInput(), waist_cm=StoredInput(), systolic_bp=StoredInput(),
        total_cholesterol=StoredInput(), hdl_cholesterol=StoredInput(),
        findrisc_missing=["profile", "weight_kg", "waist_cm"],
        framingham_missing=["profile", "systolic_bp", "total_cholesterol", "hdl_cholesterol"],
    )


def _db() -> AsyncMock:
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = profile_result
    return db


@pytest.mark.parametrize("message", [
    "Mekkora a kockázatom?",
    "Mekkora a cukorbetegség kockázatom?",
    "Mi a rizikóm szívbetegségre?",
    "What is my diabetes risk?",
    "Calculate my FINDRISC score",
    "Mennyi a Framingham pontszámom?",
])
def test_explicit_risk_questions_open_the_form(message):
    assert _is_risk_calculation_request(message)


@pytest.mark.parametrize("message", [
    "Ha 80 kg lennék, mi lenne a kockázatom?",  # hypothetical stays in memory
    "What if my systolic were 150, what is my risk?",
    "Mennyi a koleszterinem?",                  # no risk keyword
    "Hogy vagyok?",                             # fallback, not an explicit request
])
def test_other_questions_do_not_open_the_form(message):
    assert not _is_risk_calculation_request(message)


def test_fallback_still_includes_risk_context():
    """The no-keyword fallback keeps risk scores in the LLM context."""
    assert "risk" in _detect_intent("Hogy vagyok?")


@pytest.mark.asyncio
async def test_risk_request_lists_stored_inputs_without_llm():
    request = ChatRequest(message="Mekkora a kockázatom?")
    with patch.object(chat_router, "collect_inputs", AsyncMock(return_value=_empty_status())), \
         patch.object(chat_router.llm_service, "chat", AsyncMock()) as llm, \
         patch.object(chat_router.rag_service, "build_context", AsyncMock()) as rag:
        response = await chat(request=request, db=_db())

    llm.assert_not_called()
    rag.assert_not_called()
    assert response.data_request is not None
    assert response.data_request.findrisc_missing[0] == "profile"
    assert response.language == "Hungarian"
    assert "nincs adat" in response.reply


@pytest.mark.asyncio
async def test_hypothetical_question_goes_to_llm_without_form():
    request = ChatRequest(message="Ha 80 kg lennék, mi lenne a kockázatom?")
    with patch.object(chat_router, "collect_inputs", AsyncMock()) as collect, \
         patch.object(chat_router.rag_service, "build_context", AsyncMock(return_value="")), \
         patch.object(chat_router.llm_service, "chat", AsyncMock(return_value="ok")) as llm:
        response = await chat(request=request, db=_db())

    collect.assert_not_called()
    llm.assert_awaited_once()
    assert response.data_request is None


@pytest.mark.asyncio
async def test_unreadable_inputs_return_503_without_details():
    request = ChatRequest(message="What is my risk?")
    failing = AsyncMock(side_effect=RuntimeError("password=hunter2"))
    with patch.object(chat_router, "collect_inputs", failing), \
         patch.object(chat_router.llm_service, "chat", AsyncMock()) as llm:
        with pytest.raises(HTTPException) as exc_info:
            await chat(request=request, db=_db())

    assert exc_info.value.status_code == 503
    assert "hunter2" not in exc_info.value.detail
    llm.assert_not_called()


# ── Reply text ───────────────────────────────────────────────────────────────

def test_reply_shows_value_date_and_stale_marker_in_english():
    status = _empty_status()
    old = date.today() - timedelta(days=200)
    status.weight_kg = StoredInput(value=82.5, unit="kg", recorded_on=old, status="stale")

    text = format_risk_inputs(status, "English")

    assert f"Weight: 82.5 kg ({old.isoformat()}) — old measurement" in text
    assert "Waist circumference: no data" in text
    assert "FINDRISC: missing Profile (age, sex, height, questions), Weight, Waist circumference." in text


def test_reply_marks_framingham_unavailable_for_female_profile():
    status = _empty_status()
    status.profile = ProfileData(
        birth_year=1980, birth_month=1, sex="female", height_cm=165, smoking=False,
        bp_medication_ever=False, bp_medication_current=False,
        high_glucose_history=False, diabetes_diagnosed=False,
        vegetables_daily=True, physically_active=True, family_diabetes="none",
    )
    status.age = 46
    status.framingham_unavailable = "no validated Framingham risk table for women yet"

    text = format_risk_inputs(status, "Hungarian")

    assert "megvan, életkor: 46 év" in text
    assert "Framingham: nem elérhető" in text
