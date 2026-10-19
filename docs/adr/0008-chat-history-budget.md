# 0008. Tag chat turns by source and fit the history to a token budget

- **Status:** Accepted
- **Date:** 2026-10-19 (#45 at 14:10)
- **Evidence:** `backend/services/chat_history.py`,
  `backend/services/llm_service.py` (`build_messages`, `warn_if_near_window`),
  `backend/config.py` (`llm_num_ctx`), `frontend/pages/03_chat.py`;
  ARCHITECTURE invariant 3

## Context

The chat sent every earlier turn, with no limit. UI error messages went back
to the model as its own assistant turns, and so did replies the app produced
without the LLM (the stored-input list, the risk form's result). The window
was Ollama's default 4096 tokens, while the system prompt alone is about
2.3–3k tokens. On overflow, Ollama silently drops the oldest messages
(`server/prompt.go`, `chatPrompt`).

## Decision

- Every turn carries a source: `llm`, `automatic` or `error`. Error turns are
  dropped together with the question they answered. Automatic replies are
  kept with an "[Automatic reply from the app, not written by the
  assistant]" prefix.
- `num_ctx` is set explicitly to 8192. The history gets what is left after
  the 512-token reply budget, a safety margin and the estimated system prompt
  and question; the oldest turns are dropped first.
- Tokens are estimated at 2.5 characters per token. Real prompts measured
  2.68–2.78 with `qwen2.5:1.5b`, so the estimate errs high. A warning is
  logged when Ollama's `prompt_eval_count` shows it was too low.

## Alternatives considered

- **Leave trimming to Ollama:** silent and uncontrolled.
- **Summarise old turns with the LLM:** keeps more context, but costs an
  extra slow CPU call per turn.
- **Exclude automatic replies:** cleaner, but a follow-up such as "mit jelent
  ez?" ("what does this mean?") could not refer to the risk result.
- **Keep the 4096 window:** no extra memory or latency, but only one or two
  earlier turns fit.

## Consequences

- The model never reads UI error text as its own words.
- Long chats forget their oldest turns without telling the user (README,
  Known Limitations).
- The larger window costs memory (larger KV cache) and makes prompt
  processing slower on CPU.
- The character-based estimate must be re-measured for another model.
- The backend configures no logging, so the info-level "dropped N turns"
  line is not shown today; the warning is.
