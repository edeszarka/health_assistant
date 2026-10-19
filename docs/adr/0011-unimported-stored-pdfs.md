# 0011. What to do with stored PDFs that were never imported

- **Status:** Proposed
- **Date:** 2026-10-19
- **Evidence:** `backend/scripts/reimport_labs.py` (works only on uploads that
  have rows in `lab_results`), [0009](0009-retention-of-uploaded-pdfs.md)

## Context

The upload folder holds PDFs that have no rows in the database, most likely
uploaded before an earlier database reset (not verified). They are not part of any answer,
but they still contain identifying data. The re-import script only handles
uploads that already have rows, so it does not pick them up.

## Options

- **Import them:** extend the re-import script to parse files without rows
  (using the same `store_lab_results` path as an upload), so the lab history
  becomes complete.
- **Delete them:** consistent with deleting PDFs after parsing, if
  [0009](0009-retention-of-uploaded-pdfs.md) decides so.
- **Leave them:** no change; they stay unused identifying data on disk.

## Decision

Not decided. Depends on [0009](0009-retention-of-uploaded-pdfs.md); the
owner's decision is needed.
