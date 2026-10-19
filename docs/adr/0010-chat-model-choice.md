# 0010. Which chat model is the documented default

- **Status:** Proposed
- **Date:** 2026-10-19
- **Evidence:** `backend/config.py` (`ollama_model = "llama3.2:3b"`),
  `docker-compose.yml` (`OLLAMA_MODEL`, default `llama3.2:3b`), `.env.example`
  (`llama3.1:8b`), README "AI Design and Evaluation"

## Context

Three places name a chat model, and they disagree: the code and Compose
default to `llama3.2:3b`, `.env.example` suggests `llama3.1:8b`, and the
README describes `llama3.2:3b`. The local installation overrides the default
with `qwen2.5:1.5b`. All measurements recorded on 2026-10-19 (reply times,
the 2.68–2.78 characters-per-token ratio behind
[0008](0008-chat-history-budget.md)) were taken with `qwen2.5:1.5b`.

## Options

- **Make `qwen2.5:1.5b` the default:** matches what was measured; fastest on
  CPU; the weakest instruction following and Hungarian of the three.
- **Keep `llama3.2:3b`:** matches the README; slower; the token ratio and the
  reply times need re-measuring with it.
- **`llama3.1:8b`:** the best answers of the three; much slower on CPU, and
  more memory with an 8192-token window.

Whichever is chosen, the code, Compose, `.env.example` and the README should
name the same model, and the measurements should be repeated with it.

## Decision

Not decided. Owner's decision needed.
