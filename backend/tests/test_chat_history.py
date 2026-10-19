"""Tests for the chat history sent to the model: cleaning, budget, num_ctx."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import settings
from models.api_models import ChatRequest, ChatTurn
from routers import chat as chat_router
from routers.chat import chat
from services import llm_service as llm_module
from services.chat_history import (
    AUTOMATIC_MARKER,
    clean_history,
    estimate_tokens,
    fit_history,
)
from services.llm_service import build_messages, llm_service

ERROR_TEXT = "❌ Backend error: The language model is unavailable."


def _turn(role: str, content: str, source: str = "llm") -> ChatTurn:
    return ChatTurn(role=role, content=content, source=source)


# ── Cleaning ─────────────────────────────────────────────────────────────────

def test_error_turn_is_dropped_with_its_question():
    turns = [
        _turn("user", "first"), _turn("assistant", "answer"),
        _turn("user", "failed question"), _turn("assistant", ERROR_TEXT, "error"),
    ]
    assert clean_history(turns) == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
    ]


def test_automatic_reply_is_marked():
    cleaned = clean_history([_turn("user", "q"), _turn("assistant", "stored list", "automatic")])
    assert cleaned[1]["content"] == AUTOMATIC_MARKER + "stored list"


def test_old_clients_without_source_are_treated_as_llm():
    turn = ChatTurn(role="assistant", content="a")
    assert turn.source == "llm"
    assert clean_history([turn]) == [{"role": "assistant", "content": "a"}]


# ── Fitting ──────────────────────────────────────────────────────────────────

def _history(pairs: int, size: int = 100) -> list[dict[str, str]]:
    turns = []
    for i in range(pairs):
        turns.append({"role": "user", "content": f"q{i}".ljust(size)})
        turns.append({"role": "assistant", "content": f"a{i}".ljust(size)})
    return turns


def test_fit_keeps_the_newest_turns():
    turns = _history(4)
    per_turn = estimate_tokens(turns[0]["content"])
    kept, dropped = fit_history(turns, budget_tokens=per_turn * 4)
    assert [t["content"].strip() for t in kept] == ["q2", "a2", "q3", "a3"]
    assert dropped == 4


def test_fit_never_starts_with_an_assistant_turn():
    turns = _history(3)
    per_turn = estimate_tokens(turns[0]["content"])
    kept, dropped = fit_history(turns, budget_tokens=per_turn * 3)
    assert kept[0]["role"] == "user"
    assert [t["content"].strip() for t in kept] == ["q2", "a2"]
    assert dropped == 4


def test_zero_budget_gives_empty_history():
    assert fit_history(_history(2), budget_tokens=0) == ([], 4)


def test_estimate_is_on_the_high_side_of_the_measured_ratio():
    """Measured 2.68-2.78 chars/token; the estimate must not undercount."""
    assert estimate_tokens("x" * 2700) >= 2700 / 2.68


# ── LLM call ─────────────────────────────────────────────────────────────────

def _client(prompt_eval_count: int = 100) -> AsyncMock:
    resp = MagicMock()
    resp.json.return_value = {"message": {"content": "ok"}, "prompt_eval_count": prompt_eval_count}
    client = AsyncMock()
    client.post.return_value = resp
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_num_ctx_is_sent_to_ollama():
    client = _client()
    with patch("services.llm_service.httpx.AsyncClient", return_value=client):
        await llm_service.chat(message="hi", conversation_history=[], context="")
    options = client.post.call_args.kwargs["json"]["options"]
    assert options["num_ctx"] == settings.llm_num_ctx


def test_history_is_trimmed_to_the_window(caplog):
    long_history = _history(40, size=1000)  # ~32k tokens, far over the window
    with caplog.at_level(logging.INFO, logger="services.llm_service"):
        messages = build_messages("system prompt", long_history, "now")

    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "now"}
    total = sum(estimate_tokens(m["content"]) for m in messages)
    assert total <= settings.llm_num_ctx
    assert "Dropped" in caplog.text


@pytest.mark.asyncio
async def test_warning_when_prompt_exceeds_its_share_of_the_window(caplog):
    client = _client(prompt_eval_count=settings.llm_num_ctx)
    with patch("services.llm_service.httpx.AsyncClient", return_value=client), \
         caplog.at_level(logging.WARNING, logger="services.llm_service"):
        await llm_service.chat(message="hi", conversation_history=[], context="")
    assert "CHARS_PER_TOKEN may be too high" in caplog.text


@pytest.mark.asyncio
async def test_small_window_drops_history_but_keeps_system_prompt():
    client = _client()
    with patch.object(llm_module.settings, "llm_num_ctx", 3000), \
         patch("services.llm_service.httpx.AsyncClient", return_value=client):
        await llm_service.chat(message="hi", conversation_history=_history(10, size=1000), context="")
    messages = client.post.call_args.kwargs["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert len(messages) < 22


# ── Chat endpoint ────────────────────────────────────────────────────────────

def _db() -> AsyncMock:
    profile = MagicMock()
    profile.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = profile
    return db


@pytest.mark.asyncio
async def test_ui_error_turn_never_reaches_the_model():
    request = ChatRequest(
        message="hello again",
        conversation_history=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "failed"},
            {"role": "assistant", "content": ERROR_TEXT, "source": "error"},
        ],
    )
    with patch.object(chat_router.rag_service, "build_context", AsyncMock(return_value="")), \
         patch.object(chat_router.llm_service, "chat", AsyncMock(return_value="ok")) as llm:
        await chat(request=request, db=_db())

    history = llm.await_args.kwargs["conversation_history"]
    assert all(ERROR_TEXT not in turn["content"] for turn in history)
    assert [t["content"] for t in history] == ["first", "answer"]


@pytest.mark.asyncio
async def test_risk_reply_is_marked_automatic():
    status = MagicMock()
    with patch.object(chat_router, "collect_inputs", AsyncMock(return_value=status)), \
         patch.object(chat_router, "format_risk_inputs", return_value="stored inputs"), \
         patch.object(chat_router, "ChatResponse") as response_cls:
        await chat(request=ChatRequest(message="What is my risk?"), db=_db())

    assert response_cls.call_args.kwargs["source"] == "automatic"
