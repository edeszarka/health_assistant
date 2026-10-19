# 0012. Put only the asked-about and flagged lab results into the prompt

- **Status:** Accepted
- **Date:** 2026-10-19
- **Evidence:** `backend/routers/chat.py` (`select_lab_tests`,
  `format_lab_selection`, `_build_lab_trends_summary`),
  `backend/tests/test_lab_context.py`; live measurements below

## Context

With `qwen2.5:3b` on the CPU-only laptop, a lab question took ~150 s, above
the 120 s target of [0010](0010-chat-model-choice.md). 121 s of it was reading
a ~2500-token prompt at ~21–23 tokens/s. The largest part was the lab block:
every relevant test with its full history, ~1170 tokens on the live data,
whatever the question asked. The owner kept the model ("slower is acceptable,
a weaker model is not") and asked for only the asked-about labs in the prompt.
The flagged ones matter most: the lab marks them with `*` because the value is
outside the reference range, and the parser stores that as `is_flagged`.

## Decision

The lab block shows in full:

- the tests the question names, first, under "Asked about". They are matched by
  `mentioned_keys`, the same English/Hungarian matcher that picks the
  MedlinePlus references;
- every flagged test;
- when the question names no test, or asks about risk: the risk-score labs and
  rising trends.

Every other test is listed by name only on one line ("Other tests on record,
within range"). This keeps the model from calling it missing. A named test
with no result is reported as "Asked about, not on record".

## Alternatives considered

- **All labs, as before:** ~1170 tokens of lab data in every lab question;
  about 50 s of reading on this CPU.
- **Select labs by embedding similarity:** one more embedding call per
  question, and fuzzy where the keyword matcher is exact for the lab names
  in use.
- **Reorder the prompt, static parts first, for Ollama's prefix cache:** the
  static part before the data is small (~600 tokens of rules), and moving
  the rules away from the end risks a small model following them less.
  Not done; to be measured separately if needed.
- **A faster, weaker model (`qwen2.5:1.5b`):** rejected by the owner (0010).

## Consequences

- Measured live on 2026-10-19, prompt not cached:
  - the lab block went from ~1170 to ~320–510 estimated tokens;
  - the whole prompt from ~2500 to ~1100–1300 tokens;
  - reading time from 121 s to 52–59 s;
  - a whole reply took 73–81 s.
- Generation time depends on the answer's length. A question listing every
  out-of-range result took 106 s end to end, and the first question after
  Ollama had unloaded the models took 137 s.
- A follow-up that names no test ("and is that bad?") gets only the flagged
  and key labs; the earlier answer is still in the chat history. Carrying the
  last named tests forward is a possible follow-up.
- A test name the matcher does not know (e.g. an inflection that changes the
  stem) is not shown in full, only listed by name, so the model can say it
  is on record but cannot quote its value.
- The answer eval passes its own fictional lab block, so it does not measure
  this selection; `test_lab_context.py` does.
