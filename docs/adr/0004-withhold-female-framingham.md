# 0004. Withhold Framingham for women until the table is validated

- **Status:** Accepted
- **Date:** 2026-10-14 (#36, `c860181`)
- **Evidence:** `backend/services/risk_engine.py` (`_FRAMINGHAM_RISK_FEMALE`,
  `framingham_supported`), ARCHITECTURE invariant 8, README Known Limitations

## Context

The Framingham points-to-risk table for women is a placeholder copy of the
men's table. A score computed with it looks plausible but is wrong.

## Decision

`framingham_supported` allows only the validated male table. For women no
Framingham score is computed or saved, and a "what if" question gets an
explicit "Not available" with the reason. FINDRISC is unaffected.

## Alternatives considered

- **Show the score with a warning:** a number is more persuasive than its
  caveat, especially in a health context.
- **Use the male table for everyone:** silently wrong for women.
- **Implement the published women's table (Wilson et al., 1998) now:** the
  right fix, but it needs a verified source and reference cases as tests;
  until then, no score is safer than a wrong one.

## Consequences

- Women get FINDRISC only; the risk form says why Framingham is missing.
- Implementing the women's table supersedes this record.
