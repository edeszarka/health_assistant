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

## Correction (2026-11-02)

The numbers above had no committed output, and they present one measurement
twice: at top-1, with every question returning a row, recall and precision are the
same count. The re-run confirms the operating point, and its output is committed
in `backend/eval/results/retrieval_2026-11-02.txt`:

- 17 of 20 questions retrieve a relevant record (Hungarian 7 of 10, English 10 of
  10), the other 3 a wrong one, and 0 of 5 off-topic questions retrieve anything.
- At 0.62, top-2 to top-5 find 17 to 18 of 20, with 32-50% of the rows relevant.
- At 0.60, 1 of 5 off-topic questions retrieves a row. At 0.65, only 13 of 20
  questions find a relevant record (Hungarian 4 of 10).

The point was first chosen in `3d5177b` on an earlier store, at 80% recall and
precision and 2 of 5 off-topic hits. It was kept unchanged after header rows and
duplicates were removed. It was chosen and reported on the same questions, with
no held-out set. The "at most 40%" Hungarian figure comes from that commit's
message; its output was not kept, and no English figure from the same run exists.
