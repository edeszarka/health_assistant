# 0005. Set the RAG operating point by a retrieval eval (top-1, ≥ 0.62)

- **Status:** Accepted
- **Date:** 2026-10-17 (#38, `3d5177b`)
- **Evidence:** `backend/eval/retrieval_eval.py`, `backend/eval/queries.json`,
  `backend/config.py` (`rag_top_k`, `rag_similarity_threshold`), README
  "RAG Evaluation"

## Context

Retrieval returns the user's own stored records (lab results, family
history, wearable summary) as extra context. Too few results miss the record
the question is about; too many fill a small model's prompt with unrelated
records, which it then quotes.

## Decision

`rag_top_k = 1` and `rag_similarity_threshold = 0.62`, chosen with
`python -m eval.retrieval_eval`. The eval runs 20 Hungarian and English
questions plus 5 off-topic ones; relevance is decided from metadata (source
type, normalised test name), so it prints no health values. On 42 stored
records this point gave recall 85% (Hungarian 70%, English 100%), precision
85%, and no hits for the off-topic questions. Embedded texts carry nomic's
task prefixes and the report's own test names; before that, Hungarian recall
was at most 40%.

## Alternatives considered

- **More results (top-2 to top-5):** recall rose to at most 90%, but
  precision fell to 32–50%.
- **A lower threshold:** more off-topic hits, which a small model treats as
  relevant.
- **No threshold (always top-k):** off-topic questions would always retrieve
  a record.

## Consequences

- One relevant record per question in most cases; Hungarian recall is the
  weak spot (70%).
- The operating point depends on the data, the templates and the embedding
  model: after changing any of them, re-embed (`python -m scripts.reembed`)
  and re-run the eval.
- The eval measures retrieval only, not the quality of the generated answer.
  It is small (25 questions on one person's data) and is not run in CI.
