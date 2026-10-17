"""Re-import lab results from the stored upload PDFs with the current parser.

Use after a parser fix, so rows stored by an older parser (e.g. header fields
saved as results, or results it missed) are replaced. Run inside the backend
container; a dry run is the default:

    python -m scripts.reimport_labs          # counts only, writes nothing
    python -m scripts.reimport_labs --apply  # write the changes

Per upload (``lab_results.source_filename`` → ``{upload_dir}/{id}.pdf``):
- the newest upload of each distinct PDF (SHA-256) is re-parsed and replaced:
  its rows and their lab_result embeddings are deleted, then the new rows are
  stored through services.lab_ingest (the same path as a fresh upload);
- older uploads of the same PDF are duplicates: their rows are removed;
- if the PDF is missing, only rows whose name is a header field are removed;
- if parsing fails, nothing is changed.
Parsing happens before any delete, and a rerun is safe. Prints counts only,
never PDF content, names or values.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.connection import AsyncSessionLocal
from ingestion.pdf_parser import PDFParser
from models.db_models import Embedding, LabResult
from services.lab_ingest import store_lab_results

logger = logging.getLogger(__name__)


@dataclass
class Outcome:
    upload_id: str
    old_rows: int
    old_header_like: int
    new_rows: int = 0
    removed: int = 0
    stored: int = 0
    status: str = "re-import"


async def _old_rows(db: AsyncSession, upload_id: str) -> list[tuple[int, str]]:
    stmt = select(LabResult.id, LabResult.raw_name).where(
        LabResult.source_filename == upload_id
    )
    return [tuple(row) for row in (await db.execute(stmt)).all()]


async def _delete_rows(db: AsyncSession, row_ids: list[int]) -> int:
    """Delete lab rows and their lab_result embeddings; returns rows deleted."""
    if not row_ids:
        return 0
    await db.execute(
        delete(Embedding).where(
            Embedding.source_type == "lab_result", Embedding.source_id.in_(row_ids)
        )
    )
    await db.execute(delete(LabResult).where(LabResult.id.in_(row_ids)))
    await db.commit()
    return len(row_ids)


def _newest_per_file(paths: dict[str, Path]) -> dict[str, str]:
    """Map each upload id to the newest upload id holding the same PDF bytes."""
    by_hash: dict[str, list[str]] = {}
    for upload_id, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        by_hash.setdefault(digest, []).append(upload_id)
    # Upload ids start with a YYYYmmddHHMMSS timestamp, so max() is the newest.
    return {uid: max(group) for group in by_hash.values() for uid in group}


async def _handle(
    db: AsyncSession, outcome: Outcome, rows: list[tuple[int, str]],
    path: Path | None, keeper: str | None, parser: PDFParser, apply: bool,
) -> None:
    """Decide and (if ``apply``) perform the action for one upload."""
    header_ids = [rid for rid, name in rows if parser._HEADER_NAME_RE.search(name)]
    if path is None:
        outcome.status = "pdf missing: remove header rows"
        outcome.removed = await _delete_rows(db, header_ids) if apply else len(header_ids)
        return
    if keeper != outcome.upload_id:
        outcome.status = f"duplicate of {keeper[:14]}: remove"
        outcome.removed = await _delete_rows(db, [rid for rid, _ in rows]) if apply else len(rows)
        return
    try:
        report = parser.parse(path)
    except Exception as exc:
        logger.warning("Parse failed for %s: %s", outcome.upload_id, type(exc).__name__)
        outcome.status = "parse failed: kept"
        return
    outcome.new_rows = sum(r.value is not None for r in report.results)
    if not apply:
        outcome.removed = len(rows)
        return
    outcome.removed = await _delete_rows(db, [rid for rid, _ in rows])
    outcome.stored = await store_lab_results(report, outcome.upload_id, db)


async def reimport(
    db: AsyncSession, upload_dir: Path, parser: PDFParser, apply: bool
) -> list[Outcome]:
    """Plan (and with ``apply`` perform) the re-import of every stored upload."""
    upload_ids = sorted(
        (await db.execute(select(LabResult.source_filename).distinct())).scalars().all()
    )
    paths = {uid: upload_dir / f"{uid}.pdf" for uid in upload_ids}
    present = {uid: p for uid, p in paths.items() if p.exists()}
    keepers = _newest_per_file(present)
    outcomes = []
    for upload_id in upload_ids:
        rows = await _old_rows(db, upload_id)
        outcome = Outcome(
            upload_id=upload_id,
            old_rows=len(rows),
            old_header_like=sum(bool(parser._HEADER_NAME_RE.search(n)) for _, n in rows),
        )
        await _handle(db, outcome, rows, present.get(upload_id), keepers.get(upload_id), parser, apply)
        outcomes.append(outcome)
    return outcomes


def _print(outcomes: list[Outcome], apply: bool) -> None:
    print("upload (timestamp) | old rows | old header-like | new rows | removed | stored | action")
    for o in outcomes:
        stored = str(o.stored) if apply else "-"
        print(f"{o.upload_id[:14]:18} | {o.old_rows:8} | {o.old_header_like:15} | "
              f"{o.new_rows:8} | {o.removed:7} | {stored:6} | {o.status}")
    totals = (f"totals: old={sum(o.old_rows for o in outcomes)} "
              f"old_header_like={sum(o.old_header_like for o in outcomes)} "
              f"new={sum(o.new_rows for o in outcomes)} removed={sum(o.removed for o in outcomes)}")
    print(totals + (f" stored={sum(o.stored for o in outcomes)}" if apply
                    else " (dry run: nothing written; 'removed' = would remove)"))


async def main(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        outcomes = await reimport(db, Path(settings.upload_dir), PDFParser(), apply)
    _print(outcomes, apply)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    asyncio.run(main(cli.parse_args().apply))
