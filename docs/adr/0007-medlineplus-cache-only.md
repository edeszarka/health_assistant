# 0007. Use MedlinePlus in the chat from the cache only, prefetched for a fixed list

- **Status:** Accepted
- **Date:** 2026-10-19 (#43 at 11:30, #44 at 13:19)
- **Evidence:** `backend/services/medlineplus_context.py`,
  `backend/services/lab_loinc.py`, `backend/scripts/warm_medlineplus.py`,
  `backend/services/medlineplus_service.py` (`get_cached`); ARCHITECTURE
  invariants 3, 4, 5

## Context

The small chat model explained lab tests from its own memory. MedlinePlus
(U.S. National Library of Medicine) offers authoritative text per lab test
(by LOINC code) and per condition (by ICD-10 code). A lookup made while
answering a question would tell NLM which tests the user asks about or has.

## Decision

- **Lab tests:** a fixed list of 51 LOINC codes (each checked against the
  LOINC code system) is prefetched by `scripts/warm_medlineplus.py`, whatever
  the user's results are, so the requests are identical for every user.
- **Family conditions:** looked up once, by the ICD-10 code the user typed,
  when the entry is saved, as before.
- **Chat:** reads the cache only and never calls MedlinePlus. Up to three
  texts, one per MedlinePlus page, go into a separate `<reference>` block
  labelled as general text that is not about the user. The pages used are
  returned as the answer's sources.

## Alternatives considered

- **Live lookup per question:** fresh text, but each question would reveal
  the user's tests to a third party.
- **Embed MedlinePlus text in the vector store:** retrieval would mix
  external text with the user's own records (against invariant 5), and old
  versions would stay retrievable after a refresh.
- **No MedlinePlus in the chat:** keeps the model explaining tests from
  memory.

## Consequences

- No user-dependent request leaves the host because of a question.
- The text is English only; the model paraphrases it in Hungarian, and a
  small model may do so imperfectly.
- The cache is refreshed only when the script is rerun; expired text is
  still used. NLM recommends caching for 12–24 hours.
- Several codes share one page (e.g. HDL and LDL → cholesterol), so the
  answer may cover a test less specifically than the user asked.
