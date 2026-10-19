# 0002. Parse lab reports with rules and a dictionary, not with an LLM

- **Status:** Accepted
- **Date:** 2026-03-11 (`9c1a1c4`, "pdf parser debugged")
- **Evidence:** `backend/ingestion/pdf_parser.py`, `backend/ingestion/lab_normalizer.py`,
  `backend/ingestion/unit_converter.py`; the first parser in `a4d2f5e`

## Context

The first parser (initial commit `a4d2f5e`, 2026-03-05) sent the PDF text to
the local LLM and asked for structured lab values as JSON. On 2026-03-11 it
was replaced by a rule-based parser. The commit message does not record why;
the reasons below are reconstructed from the code and from later fixes, and
are marked as such.

## Decision

Lab values are extracted with pdfplumber and regular expressions, test names
are mapped to normalised keys by a dictionary (`LabNormalizer`), and units
are converted only from units that are recognised (ARCHITECTURE invariant 1).
No LLM is involved in turning a PDF into stored values.

## Alternatives considered

- **LLM extraction (the original design):** handles unseen layouts, but
  (reconstructed) a small local model can drop, invent or mis-assign numbers
  and units without any signal, the output is not reproducible, and
  extraction would take minutes per report on CPU.
- **LLM as a fallback for unknown test names only:** still listed in the
  README roadmap; not implemented.

## Consequences

- Extraction is deterministic, fast and testable; a wrong value has a code
  path that can be fixed and covered by a test (e.g. header rows, #39).
- Only known layouts work (two today); an unknown layout yields few or no
  rows, and every new layout or test name needs code or dictionary changes.
- Parsed values are not reviewed by a human (README, Known Limitations).
