# 0010. Use qwen2.5:3b as the default chat model

- **Status:** Accepted
- **Date:** 2026-10-19 (proposed in #46; measured with the answer eval from #47)
- **Evidence:** `backend/eval/answer_eval.py`, `backend/eval/answer_cases.json`;
  `backend/config.py` (`ollama_model`), `docker-compose.yml`, `.env.example`

## Context

Three places named a chat model and disagreed: the code and Compose defaulted
to `llama3.2:3b`, `.env.example` suggested `llama3.1:8b`, and the local
installation ran `qwen2.5:1.5b`. Nothing measured answer quality.

The owner's requirement: sensible English answers within a median of 120 s
per reply on the laptop the app runs on (AMD Ryzen 5 PRO 4650U, 6 cores,
16 GB RAM, CPU-only inference, 7.8 GB for the Docker VM). Hungarian answers
are reported but do not decide.

## Measurement

Answer eval, 2026-10-19: 16 English and 4 Hungarian questions over fictional
data, each run 3 times at the chat's sampling settings, through the real
system prompt. The deterministic checks (expected values quoted, no number
that is not in the prompt, missing data reported as missing, an injected
instruction not followed, the answer in the question's language) are in
`backend/eval/answer_scoring.py`.

| Model | English pass rate | Expected values | Answers with a number not in the prompt | "Not available" when data is missing | Median / p90 reply | Hungarian pass rate |
|---|---|---|---|---|---|---|
| **qwen2.5:3b** | **92%** | **100%** | 8% | 98% | **23 s / 43 s**¹ | **58%** |
| llama3.2:3b | 92% | 96% | **4%** | **100%** | 20 s / 64 s² | 50% |
| qwen2.5:1.5b | 81% | 92% | 15% | 94% | 11 s / 21 s | 17% |

¹ Measured alone (16 English answers). ² The `llama3.2:3b` and `qwen2.5:3b`
runs partly overlapped; the alone-run of `qwen2.5:3b` (23 s) matched its
overlapped median (24 s), so the overlap changed little.

## Decision

The default chat model is `qwen2.5:3b`, in code, Compose and `.env.example`.

The pre-agreed criterion was: the best English pass rate, then the fewest
answers with a number not in the prompt, then the faster model. It picks
`llama3.2:3b`, by 2 answers out of 48 on the second key, after a tie on the
first. The owner chose `qwen2.5:3b` instead, because the failures differ in
kind:

- `qwen2.5:3b` failed by quoting general reference ranges from memory
  (e.g. "TSH is usually between 0.4 and 4.0 mIU/L") for a test the user does
  not have.
- `llama3.2:3b` invented a value for the user's own LDL, attributed unsourced
  vitamin D ranges to MedlinePlus ("according to MedlinePlus…"), and twice
  refused to answer a plain question ("I can't answer that").

In a health assistant, an invented value and a false source attribution are
worse than an unsourced general range. A 2-answer difference is also within
the run-to-run variation the eval showed.

## Alternatives considered

- **`llama3.2:3b`:** what the criterion picked; rejected for the reasons above.
- **`qwen2.5:1.5b`:** fastest (median 11 s), but the lowest pass rate (81%),
  the most numbers not in the prompt (15%), and near-unusable Hungarian.
- **A 7–8B model (e.g. `llama3.1:8b`):** not measured; with an 8192-token
  window it would be tight in the 7.8 GB Docker VM and several times slower
  on this CPU.

## Correction (2026-10-19, after the live check)

The latencies above are too low for real use. All eval cases share most of
their fictional context, so Ollama served most of each prompt from its
prompt cache, and the eval's prompts (~1100 tokens) are half the size of a
real one with a full lab history (~2300–2600 tokens). Measured without the
cache (`--cold`, English cases):

| Model | Median / p90 reply | Reading / writing speed | Pass rate |
|---|---|---|---|
| qwen2.5:3b | 64 s / 73 s | 23 / 5.8 tokens/s | 94% |
| qwen2.5:1.5b | 31 s / 42 s | 46 / 11 tokens/s | 69% |

A live lab question with a ~2500-token prompt took 150 s with `qwen2.5:3b`
(121 s reading the prompt, 27 s writing), above the 120 s target; a small
prompt took 32 s, and the same question again (cached) 31 s. The decision
stands for now, because reading the prompt dominates and the prompt can be
made shorter and more cacheable. If that does not bring a lab question under
120 s, this record is superseded.

## Consequences

- One model name everywhere. A local `.env` that sets `OLLAMA_MODEL` still
  overrides it.
- The token estimate of [0008](0008-chat-history-budget.md) still holds:
  `qwen2.5:3b` shares the Qwen2.5 tokenizer and measured the same 2.68–2.78
  characters per token.
- Replies take about twice as long as with `qwen2.5:1.5b`.
- The eval cannot catch a wrong claim built from correct numbers (README,
  "Answer Evaluation"), so the pass rate is an upper bound on correctness.
- Changing the model again means re-running the answer eval and recording
  the result in a new ADR that supersedes this one.
