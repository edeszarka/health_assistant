"""Upload router: lab PDF and Samsung Health ZIP ingestion."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.connection import get_db
from backend.config import settings
from backend.ingestion.pdf_parser import PDFParser
from backend.ingestion.lab_normalizer import LabNormalizer
from backend.ingestion.samsung_parser import SamsungHealthParser
from backend.models.db_models import LabResult, SamsungHealthMetric
from backend.services.rag_service import rag_service

router = APIRouter()
pdf_parser = PDFParser()
lab_norm = LabNormalizer()
samsung_parser = SamsungHealthParser()


@router.post("/pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a lab result PDF, extract values via LLM, persist to DB and embed in pgvector.

    Args:
        file: The uploaded PDF file.
        db: Async DB session.

    Returns:
        Summary of extracted and stored lab results.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")

    content = await file.read()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{uuid.uuid4().hex}_{file.filename}"
    saved_path.write_bytes(content)

    try:
        raw_labs = await pdf_parser.parse_lab_results_from_bytes(content, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Lab extraction failed: {exc}")

    stored = 0
    for lab in raw_labs:
        try:
            normalised_name = lab_norm.normalize(lab.get("raw_name", ""))
            ref_low = lab.get("ref_range_low")
            ref_high = lab.get("ref_range_high")
            value = float(lab.get("value", 0))
            is_flagged = False
            if ref_low is not None and ref_high is not None:
                is_flagged = not (float(ref_low) <= value <= float(ref_high))

            from datetime import date
            raw_date = lab.get("test_date")
            test_date = None
            if raw_date:
                try:
                    test_date = date.fromisoformat(raw_date)
                except ValueError:
                    pass

            row = LabResult(
                test_name=normalised_name,
                raw_name=lab.get("raw_name", ""),
                value=value,
                unit=lab.get("unit", ""),
                ref_range_low=ref_low,
                ref_range_high=ref_high,
                is_flagged=is_flagged,
                test_date=test_date,
                source_filename=file.filename,
            )
            db.add(row)
            await db.flush()

            # Embed
            embed_text = (
                f"Lab result: {normalised_name} = {value} {lab.get('unit', '')}. "
                f"{'FLAGGED OUT OF RANGE.' if is_flagged else 'Within reference range.'}"
            )
            await rag_service.store_embedding("lab_result", row.id, embed_text, db)
            stored += 1
        except Exception:
            continue

    await db.commit()
    return {"filename": file.filename, "extracted": len(raw_labs), "stored": stored}


@router.post("/samsung")
async def upload_samsung(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload Samsung Health ZIP export, extract metrics, store in DB, embed weekly summaries.

    Args:
        file: The uploaded ZIP file.
        db: Async DB session.

    Returns:
        Summary of extracted metrics.
    """
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files accepted.")

    content = await file.read()
    try:
        metrics = samsung_parser.parse_zip_bytes(content, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Samsung parsing failed: {exc}")

    stored = 0
    for m in metrics:
        try:
            row = SamsungHealthMetric(
                metric_type=m.metric_type,
                value=m.value,
                recorded_at=m.recorded_at,
                source_file=file.filename,
            )
            db.add(row)
            stored += 1
        except Exception:
            continue

    await db.commit()

    # Embed a weekly summary of steps (as an example)
    if stored > 0:
        summary = f"Samsung Health import: {stored} metrics from '{file.filename}'."
        await rag_service.store_embedding("samsung_summary", None, summary, db)

    return {"filename": file.filename, "metrics_extracted": len(metrics), "stored": stored}
