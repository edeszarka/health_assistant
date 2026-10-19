"""Prepare the conversation history that is sent to the chat model.

The client sends every earlier turn. Two things must not reach the model as
its own words: UI error messages (dropped, with the question they answered)
and replies the app produced without the LLM (kept, but marked). The rest is
then fitted into a token budget, dropping the oldest turns first, so the
trimming is deliberate and logged instead of left to Ollama, which silently
drops old messages when the window overflows.
"""
from __future__ import annotations

import math
from typing import Iterable

from models.api_models import ChatTurn

# Characters per token for this app's prompts, measured on 2026-10-19 with
# qwen2.5:1.5b: four real chat prompts (6254-6864 characters, Hungarian and
# English text with lab names and numbers) gave 2.68-2.78 characters per
# Ollama ``prompt_eval_count`` token. Rounded down so the estimate is high.
CHARS_PER_TOKEN = 2.5

AUTOMATIC_MARKER = "[Automatic reply from the app, not written by the assistant] "


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` (deliberately on the high side)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def clean_history(turns: Iterable[ChatTurn]) -> list[dict[str, str]]:
    """Drop failed exchanges and mark replies the model did not write.

    An ``error`` turn is a UI error message; it is dropped together with the
    user turn right before it, which the error answered. An ``automatic``
    turn is kept with ``AUTOMATIC_MARKER`` in front.

    Args:
        turns: The client-supplied history, oldest first.

    Returns:
        ``{"role", "content"}`` dicts ready for the chat model.
    """
    cleaned: list[dict[str, str]] = []
    for turn in turns:
        if turn.source == "error":
            if cleaned and cleaned[-1]["role"] == "user":
                cleaned.pop()
            continue
        content = turn.content
        if turn.source == "automatic":
            content = AUTOMATIC_MARKER + content
        cleaned.append({"role": turn.role, "content": content})
    return cleaned


def fit_history(
    turns: list[dict[str, str]], budget_tokens: int
) -> tuple[list[dict[str, str]], int]:
    """Keep the newest turns that fit the budget.

    Turns are dropped from the oldest end, and the kept history never starts
    with an assistant turn (an answer without its question).

    Args:
        turns: Cleaned history, oldest first.
        budget_tokens: Tokens available for the history.

    Returns:
        ``(kept_turns, dropped_count)``.
    """
    kept: list[dict[str, str]] = []
    used = 0
    for turn in reversed(turns):
        cost = estimate_tokens(turn["content"])
        if used + cost > budget_tokens:
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    while kept and kept[0]["role"] == "assistant":
        kept.pop(0)
    return kept, len(turns) - len(kept)
