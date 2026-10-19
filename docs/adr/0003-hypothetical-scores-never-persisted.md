# 0003. Never persist hypothetical ("what if") risk scores

- **Status:** Accepted
- **Date:** 2026-09-19 (#20, `ea01987`); locked by a test in #34 (2026-10-14)
- **Evidence:** `backend/services/risk_score_service.py` (module docstring),
  `backend/routers/chat.py` (`_build_risk_scores`), test
  `test_hypothetical_scores_are_never_persisted`; ARCHITECTURE invariant 2

## Context

The chat can recalculate FINDRISC and Framingham for a "what if" question
("ha 80 kg lennék…" — "if I weighed 80 kg…" — or "what if my systolic were 150"). Baseline scores are
saved to `risk_scores`, which the dashboard and the recommendations read.

## Decision

Hypothetical recalculations are computed in memory and returned only in the
chat answer. Only baseline scores, computed from stored measurements by
`compute_baseline_scores`, are persisted.

## Alternatives considered

- **Persist them with a "hypothetical" flag:** keeps a history of scenarios,
  but every reader of `risk_scores` would have to filter correctly, and one
  missed filter would show an invented value as a measurement.
- **Not supporting "what if" questions:** simpler, but removes a useful
  explanation of how each factor moves the score.

## Consequences

- The dashboard and the recommendations can trust every stored score.
- A scenario cannot be revisited later; the user has to ask again.
- An explicit risk question opens the input form, while a "what if" question
  keeps this in-memory path ([0006](0006-profile-model-and-in-chat-input.md)).
