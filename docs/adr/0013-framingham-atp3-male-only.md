# 0013. Score Framingham with the ATP III male table only, and withhold it for diabetes

- **Status:** Accepted
- **Date:** 2026-11-02
- **Evidence:** `backend/services/risk_engine.py` (`framingham_unavailable_reason`,
  `calculate_framingham`), `backend/tests/test_risk_published_tables.py`,
  ARCHITECTURE invariant 8. Supersedes [0004](0004-withhold-female-framingham.md).

## Context

An audit compared the calculator with the published point table and found that
the male score was wrong:

- Every smoker got a flat 8 points; the table scales them from 8 to 1 by age.
  A 55-year-old male smoker got 25% instead of 16%.
- Diabetes added 11 points. The table has no diabetes item, because ATP III
  treats diabetes as a coronary heart disease risk equivalent.
- 17 points or more were clamped to 25%; the table says 30% or more.
- An age below the table's range fell into its oldest band.

The code and documents cited Wilson et al. 1998 and called the male table
validated. Its point values are the NCEP ATP III point score, and no test checked
them. The female tables were an unverified placeholder that callers already
withheld.

## Decision

The score uses the ATP III point table for men aged 20-79. No score is shown or
saved for women, for diagnosed diabetes, or outside that age range; the user gets
the reason instead. The engine itself refuses an unsupported sex or age. Diabetes
is checked by the callers, because the engine no longer takes it as an input. The
female tables are removed.

The table's open-ended rows are stored as their nearest number, so the schema does
not change: "<1%" as 1, and "30% or more" as 30 with the category
"High (30% or more)".

## Alternatives considered

- **Show a "high risk" category without a percentage for diabetes:** more
  informative clinically, but `risk_scores.score_value` is a required number, so
  it needs a schema and API change.
- **Score diabetics without any diabetes points:** the smallest change, but it can
  show a person with diabetes a misleadingly low number.
- **Implement the women's table now:** needs a verified source and its own tests;
  no score is safer than an unverified one. It would need a new record.

## Consequences

- Tests assert exact table values, not ranges. They are transcribed from the
  table and contain no published worked patient examples, so they show that the
  code matches the table, not that the score predicts risk.
- The Framingham values were compared with Table B1 of the NCEP ATP III Executive
  Summary on 2026-11-02, and all of them match. An AI assistant (Gemini) read the
  source for the owner, with quotes; no person checked it line by line.
- The FINDRISC code is the later 26-point questionnaire. The same comparison showed
  that it is not the score in Lindström & Tuomilehto 2003, which runs from 0 to 20,
  has no family history item and has no 10-year risk bands. The 20-point fix rests
  on secondary sources (LOINC 97064-0), and the questionnaire's own primary source
  has not been checked.
- Women, people with diagnosed diabetes and people outside 20-79 get no Framingham
  score. FINDRISC is unaffected by this record.
- Existing `risk_scores` rows are not recalculated. A profile that is now withheld
  gets no new row, so its old value stays on the dashboard until that row is
  deleted.
