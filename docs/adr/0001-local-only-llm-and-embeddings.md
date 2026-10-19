# 0001. Run the LLM and the embeddings locally; health data never leaves the host

- **Status:** Accepted
- **Date:** 2026-03-05 (initial commit `a4d2f5e`; hardened in #27 and #31)
- **Evidence:** `docker-compose.yml` (`ollama` service), `backend/config.py`
  (`ollama_base_url`, `ollama_model`, `embed_model`), ARCHITECTURE invariants 4, 6, 7

## Context

The assistant reads one person's lab results, blood pressure, wearable data and
family history. These are special-category personal data. The project is a
single-user tool that runs on the owner's machine.

## Decision

Both the chat model and the embedding model are served by Ollama in a local
container, and the backend talks to it over the Compose network. The only
external call is MedlinePlus, which receives lookup terms, never records
(invariant 4). Published ports are bound to `127.0.0.1` (#31) and Streamlit
telemetry is off (#27), so nothing else leaves the host.

## Alternatives considered

- **A hosted LLM API (e.g. OpenAI, Anthropic):** better answers and much lower
  latency, but every prompt would carry the user's health data to a third
  party.
- **A hosted embedding API (e.g. OpenAI `text-embedding-3-small`):** the same
  data-transfer problem for every stored record and every question.
- **No LLM at all (rule-based answers only):** no privacy risk, but no
  free-form questions in Hungarian or English.

## Consequences

- Answers are slow on CPU: with the default `qwen2.5:3b`, ~30 s for a small
  prompt and 130–150 s for a lab question with a ~2500-token prompt that is
  not cached (measured 2026-10-19; see the correction in
  [0010](0010-chat-model-choice.md)).
- Only small models are practical (3B parameters; see
  [0010](0010-chat-model-choice.md)), so answer quality, instruction
  following and Hungarian output are limited. The prompt therefore gets pre-computed numbers and
  explicit rules instead of asking the model to reason over raw data.
- External reference text (MedlinePlus) has to be fetched without revealing
  the user's data; see [0007](0007-medlineplus-cache-only.md).
