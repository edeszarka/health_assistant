# Architecture Decision Records

Each record explains one decision that had real alternatives: the context, what
was decided, what else was considered, and the consequences. What the system
does today, and the rules it must keep, are in
[ARCHITECTURE.md](../../ARCHITECTURE.md); the records explain why.

Records 0001–0008 were written retroactively on 2026-10-19. Their date is when
the decision reached `main`, taken from the git history. A record is never
rewritten when a decision changes: a new record supersedes it, and the old
one's status says so.

Status values: **Proposed** (open, needs the owner's decision), **Accepted**,
**Superseded by NNNN**.

| # | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-local-only-llm-and-embeddings.md) | Run the LLM and the embeddings locally; health data never leaves the host | Accepted | 2026-03-05 |
| [0002](0002-lab-parsing-without-llm.md) | Parse lab reports with rules and a dictionary, not with an LLM | Accepted | 2026-03-11 |
| [0003](0003-hypothetical-scores-never-persisted.md) | Never persist hypothetical ("what if") risk scores | Accepted | 2026-09-19 |
| [0004](0004-withhold-female-framingham.md) | Withhold Framingham for women until the table is validated | Accepted | 2026-10-14 |
| [0005](0005-rag-operating-point-by-eval.md) | Set the RAG operating point by a retrieval eval (top-1, ≥ 0.62) | Accepted | 2026-10-17 |
| [0006](0006-profile-model-and-in-chat-input.md) | Profile model and collecting risk inputs through an in-chat form | Accepted | 2026-10-19 |
| [0007](0007-medlineplus-cache-only.md) | Use MedlinePlus in the chat from the cache only, prefetched for a fixed list | Accepted | 2026-10-19 |
| [0008](0008-chat-history-budget.md) | Tag chat turns by source and fit the history to a token budget | Accepted | 2026-10-19 |
| [0009](0009-retention-of-uploaded-pdfs.md) | Keep or delete uploaded lab PDFs after parsing | Proposed | 2026-10-19 |
| [0010](0010-chat-model-choice.md) | Which chat model is the documented default | Proposed | 2026-10-19 |
| [0011](0011-unimported-stored-pdfs.md) | What to do with stored PDFs that were never imported | Proposed | 2026-10-19 |

New records start from [template.md](template.md). Write one when a change
chooses between real alternatives; small fixes do not need one.
