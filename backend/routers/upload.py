"""Upload router: lab PDF and Samsung Health ZIP ingestion."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import List
from datetime import datetime, date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import get_db
from config import settings
from ingestion.pdf_parser import PDFParser
from ingestion.samsung_parser import SamsungHealthParser, SamsungHealthReport
from models.db_models import SamsungHealthMetric
from services.lab_ingest import store_lab_results
from services.rag_service import rag_service

logger = logging.getLogger(__name__)

router = APIRouter()
pdf_parser = PDFParser()
samsung_parser = SamsungHealthParser()


@router.post("/pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a lab result PDF, extract values with the PDF parser, persist to DB and embed in pgvector.

    Args:
        file: The uploaded PDF file.
        db: Async DB session.

    Returns:
        Summary of extracted and stored lab results.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")

    # Keep the original filename in memory for the user-facing response only.
    # Persisted identifiers must not embed it: an uploaded filename can contain
    # the patient's real name.
    original_filename = file.filename
    upload_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}"

    content = await file.read()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{upload_id}.pdf"
    saved_path.write_bytes(content)

    try:
        report = pdf_parser.parse(saved_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Lab extraction failed: {exc}")

    stored = await store_lab_results(report, upload_id, db)

    await db.commit()
    logger.info(
        "Extracted %d results, stored %d results for %s", len(report.results), stored, upload_id
    )
    return {
        "filename": original_filename,
        "extracted": len(report.results),
        "stored": stored,
        "warnings": report.parse_errors,
    }


@router.post("/samsung")
async def upload_samsung(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload one Samsung Health export ZIP, extract metrics, store in DB.

    The ZIP is parsed in memory and never written to disk, so the
    client-supplied filename cannot steer a write path (path traversal) and
    the export, whose name carries the Samsung account name, is not retained.

    Args:
        files: Exactly one Samsung Health export ZIP.
        db: Async DB session.

    Returns:
        Summary of extracted metrics.
    """
    if len(files) != 1 or not (files[0].filename or "").lower().endswith(".zip"):
        raise HTTPException(
            status_code=400, detail="Upload exactly one Samsung Health export ZIP."
        )
    original_filename = files[0].filename
    # Persisted identifier; the original filename is returned to the caller only.
    source_name = f"samsung_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}"

    try:
        metrics = samsung_parser.parse_zip_bytes(await files[0].read())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Samsung parsing failed: {exc}")
    report = SamsungHealthReport(metrics=metrics)

    stored = 0
    for ds in report.daily_summaries():
        try:
            raw_date = ds["date"]
            if isinstance(raw_date, str):
                record_date = datetime.fromisoformat(raw_date)
            else:
                record_date = raw_date

            if isinstance(record_date, date) and not isinstance(record_date, datetime):
                record_date = datetime.combine(record_date, datetime.min.time())

            metrics_to_store = {
                "steps": ds.get("steps"),
                "distance_m": ds.get("distance_m"),
                "active_time_min": ds.get("active_time_min"),
                "active_calories": ds.get("active_calories"),
                "water_ml": ds.get("water_ml"),
                "weight_kg": ds.get("weight_kg"),
                "bmi": ds.get("bmi"),
                "heart_rate": ds.get("heart_rate"),
                "sleep_minutes": ds.get("sleep_minutes"),
            }
            
            for m_type, m_val in metrics_to_store.items():
                if m_val is not None:
                    stmt = pg_insert(SamsungHealthMetric).values(
                        metric_type=m_type,
                        value=float(m_val),
                        recorded_at=record_date,
                        source_file=source_name
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["metric_type", "recorded_at"],
                        set_={"value": stmt.excluded.value, "source_file": stmt.excluded.source_file}
                    )
                    await db.execute(stmt)
                    stored += 1
        except Exception as exc:
            logger.warning(
                "Skipping Samsung metrics for %s: %s", ds.get("date"), type(exc).__name__
            )
            continue

    await db.commit()

    if stored > 0:
        overall_summary = report.summary()
        await rag_service.store_embedding("samsung_summary", None, overall_summary, db)

    return {"filename": original_filename, "metrics_extracted": len(report.daily_summaries()), "stored": stored}
