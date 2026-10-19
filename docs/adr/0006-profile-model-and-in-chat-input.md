# 0006. Profile model and collecting risk inputs through an in-chat form

- **Status:** Accepted
- **Date:** 2026-10-19 (#41 at 10:39, #42 at 10:59)
- **Evidence:** `backend/models/db_models.py` (`UserProfile`),
  `backend/services/risk_inputs.py`, `backend/routers/risk.py`,
  `backend/routers/chat.py` (`_is_risk_calculation_request`),
  `frontend/risk_form.py`; ARCHITECTURE invariant 1

## Context

FINDRISC and Framingham never ran: they need a profile, and nothing could
create one. The old profile stored a plain `age`, which goes stale, kept
weight and waist as single profile values, and used one answer for
questions the two scores define differently. FINDRISC also scored a missing
BMI or waist as 0 points, which under-estimates the risk.

## Decision

- **Profile:** birth year and month (age is derived, at most one month
  early), biological sex, height, and the yes/no risk questions. Questions
  that differ between the scores are separate: BP medication *ever*
  (FINDRISC) vs *currently* (Framingham); high glucose *ever* (FINDRISC) vs
  *diagnosed* diabetes (Framingham). Family diabetes is none, second degree
  or first degree.
- **Measurements:** weight and waist are dated rows, so history is kept and
  the latest value is used.
- **Missing inputs:** FINDRISC is skipped without age, sex, BMI or waist,
  like Framingham, instead of scoring them as 0.
- **Input:** an explicit risk question in the chat is answered without the
  LLM. The reply lists each stored input with its date, or "no data", and
  opens a form prefilled with those values. Saving stores the values, then
  computes and saves the scores.

## Alternatives considered

- **Store the age:** no schema change, but silently wrong a year later, and
  the FINDRISC and Framingham age bands depend on it.
- **Full date of birth:** exact, but more identifying than needed.
- **Weight as a profile field:** simpler, but no history, and a second source
  next to the wearable import.
- **Free-text input in the chat** ("waist 92, weight 81.5"): more natural, but
  parsing Hungarian free text with a small model is brittle, and a "what if"
  question is hard to tell from a real measurement.
- **A separate profile page:** works, but the user asked for the data where
  the question is asked.

## Consequences

- Scores run only with complete inputs, so a score can be missing instead of
  too low.
- Every message with a risk keyword opens the form, including follow-ups
  (README, Known Limitations).
- The schema change needed a one-off migration of the empty table
  (`scripts/migrate_user_profile.py`).
