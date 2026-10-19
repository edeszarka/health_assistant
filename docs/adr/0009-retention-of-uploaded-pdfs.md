# 0009. Keep or delete uploaded lab PDFs after parsing

- **Status:** Proposed
- **Date:** 2026-10-19
- **Evidence:** `backend/routers/upload.py` (PDF saved under a generated name),
  `backend/config.py` (`upload_dir`), `backend/scripts/reimport_labs.py`, README
  Known Limitations ("PII handling")

## Context

Uploaded lab PDFs are kept on disk unchanged. The database stores only a
generated upload identifier, never the original filename, but the PDF itself
contains the patient's name, date of birth, social-security number and
address in plain text. It is the largest store of identifying data in the
system. The re-import script (`scripts/reimport_labs.py`) relies on these
files to re-parse reports after a parser fix (#39).

## Options

- **Keep the PDFs (today):** re-import after parser fixes stays possible; the
  identifying data stays on disk unencrypted.
- **Delete each PDF after a successful parse:** removes the identifying data;
  a parser fix then needs the user to upload the report again, and the
  re-import script no longer works.
- **Keep them encrypted at rest:** keeps re-import, protects the files if the
  disk or a backup leaks; needs key management, and the key is on the same
  machine.
- **Keep only a redacted copy:** removing names and identifiers from PDFs
  reliably is hard and could damage the lab table the parser reads.

## Decision

Not decided. Owner's decision needed; this record is updated to Accepted, or
superseded, when it is made.
