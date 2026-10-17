"""Persist parsed lab results and their RAG embeddings.

Shared by the PDF upload route and scripts/reimport_labs.py, so a fresh
upload and a re-import store rows the same way.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ingestion.pdf_parser import LabValue, ParsedLabReport
from models.db_models import LabResult
from services.embedding_text import lab_result_text
from services.rag_service import rag_service

logger = logging.getLogger(__name__)


async def _store_one(
    lab: LabValue, test_date: Optional[date], upload_id: str, db: AsyncSession
) -> None:
    row = LabResult(
        test_name=lab.normalized_name,
        raw_name=lab.raw_name,
        value=lab.value,
        unit=lab.unit,
        ref_range_low=lab.ref_range_low,
        ref_range_high=lab.ref_range_high,
        is_flagged=lab.is_flagged,
        test_date=test_date,
        source_filename=upload_id,
    )
    db.add(row)
    await db.flush()
    text = lab_result_text(
        lab.raw_name, lab.normalized_name, lab.value, lab.unit, lab.is_flagged
    )
    await rag_service.store_embedding("lab_result", row.id, text, db)


async def store_lab_results(
    report: ParsedLabReport, upload_id: str, db: AsyncSession
) -> int:
    """Store every parsed lab value of one upload with its embedding.

    Rows without a numeric value are skipped. A row that fails is logged by
    test name and error type only (the exception text can contain the value)
    and the rest continue.

    Args:
        report: Parser output for one PDF.
        upload_id: Generated upload identifier stored as ``source_filename``.
        db: Async DB session. ``store_embedding`` commits after each row.

    Returns:
        The number of rows stored.
    """
    sample_date = report.patient.sample_date
    test_date = sample_date.date() if sample_date else None
    stored = 0
    for lab in report.results:
        if lab.value is None:
            continue
        try:
            await _store_one(lab, test_date, upload_id, db)
            stored += 1
        except Exception as exc:
            logger.warning(
                "Failed to store lab result %s: %s", lab.normalized_name, type(exc).__name__
            )
    return stored
