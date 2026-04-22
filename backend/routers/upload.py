"""Upload router: lab PDF and Samsung Health ZIP ingestion."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import List, Optional
from datetime import datetime, date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from config import settings
from ingestion.pdf_parser import PDFParser
from ingestion.lab_normalizer import LabNormalizer
from ingestion.samsung_parser import SamsungHealthParser
from ingestion.zepp_parser import ZeppParser
from models.db_models import LabResult, SamsungHealthMetric
from services.rag_service import rag_service

router = APIRouter()
pdf_parser = PDFParser()
lab_norm = LabNormalizer()
samsung_parser = SamsungHealthParser()
zepp_parser = ZeppParser()


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
        report = pdf_parser.parse(saved_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Lab extraction failed: {exc}")

    stored = 0
    for lab in report.results:
        try:
            normalised_name = lab.normalized_name
            value = lab.value
            
            if value is None:
                continue  # Skip if we can't parse the value

            ref_low = lab.ref_range_low
            ref_high = lab.ref_range_high
            is_flagged = lab.is_flagged

            test_date = None
            if report.patient.sample_date:
                test_date = report.patient.sample_date.date()

            row = LabResult(
                test_name=normalised_name,
                raw_name=lab.raw_name,
                value=value,
                unit=lab.unit,
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
                f"Lab result: {normalised_name} = {value} {lab.unit}. "
                f"{'FLAGGED OUT OF RANGE.' if is_flagged else 'Within reference range.'}"
            )
            await rag_service.store_embedding("lab_result", row.id, embed_text, db)
            stored += 1
        except Exception as e:
            print(f"Failed to store lab result {lab}: {e}")
            continue

    await db.commit()
    print(f"[UPLOAD] Extracted {len(report.results)} results, stored {stored} results for {file.filename}")
    return {"filename": file.filename, "extracted": len(report.results), "stored": stored}


@router.post("/samsung")
async def upload_samsung(
    files: List[UploadFile] = File(...),
    # password: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload Samsung Health ZIP or multiple CSVs, extract metrics, store in DB.

    Args:
        files: One ZIP file or multiple CSV files.
        password: Password if encrypted (not usually for Samsung, but supported).
        db: Async DB session.

    Returns:
        Summary of extracted metrics.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    upload_dir = Path(settings.upload_dir) / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    is_zip = False
    source_name = "samsung_upload"
    for file in files:
        if file.filename.lower().endswith(".zip"):
            is_zip = True
            source_name = file.filename
        file_path = upload_dir / file.filename
        file_path.write_bytes(await file.read())

    try:
        current_path = upload_dir / source_name if is_zip else upload_dir
        # report = samsung_parser.parse(current_path, password=password)
        report = samsung_parser.parse(current_path)
        if not is_zip:
            source_name = "multiple_csvs"
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Samsung parsing failed: {exc}")

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
            }
            
            for m_type, m_val in metrics_to_store.items():
                if m_val is not None:
                    db.add(SamsungHealthMetric(
                        metric_type=m_type,
                        value=float(m_val),
                        recorded_at=record_date,
                        source_file=source_name
                    ))
                    stored += 1
        except Exception:
            continue

    await db.commit()

    if stored > 0:
        overall_summary = report.summary()
        await rag_service.store_embedding("samsung_summary", None, overall_summary, db)

    return {"filename": source_name, "metrics_extracted": len(report.daily_summaries()), "stored": stored}


@router.post("/zepp")
async def upload_zepp(
    files: List[UploadFile] = File(...),
    password: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload Zepp Life ZIP or multiple CSVs, extract metrics, store in DB.

    Args:
        files: One ZIP file or multiple CSV files.
        password: Password for the encrypted zip (default test is TIHFqBtV).
        db: Async DB session.

    Returns:
        Summary of extracted metrics.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    upload_dir = Path(settings.upload_dir) / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    is_zip = False
    source_name = "zepp_upload"
    for file in files:
        if file.filename.lower().endswith(".zip"):
            is_zip = True
            source_name = file.filename
        file_path = upload_dir / file.filename
        file_path.write_bytes(await file.read())

    try:
        current_path = upload_dir / source_name if is_zip else upload_dir
        report = zepp_parser.parse(current_path, password=password)
        # report = zepp_parser.parse(current_path)
        if not is_zip:
            source_name = "multiple_csvs"
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Zepp parsing failed: {exc}")

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
                "resting_hr": ds.get("resting_hr"),
                "sleep_total_min": ds.get("sleep_total_min"),
                "sleep_deep_min":  ds.get("sleep_deep_min"),
                "sleep_light_min": ds.get("sleep_light_min"),
                "sleep_rem_min":   ds.get("sleep_rem_min"),
                "avg_spo2":        ds.get("avg_spo2"),
                "avg_stress":      ds.get("avg_stress"),
                "weight_kg":       ds.get("weight_kg"),
                "bmi":             ds.get("bmi"),
            }
            
            for m_type, m_val in metrics_to_store.items():
                if m_val is not None:
                    db.add(SamsungHealthMetric(
                        metric_type=m_type,
                        value=float(m_val),
                        recorded_at=record_date,
                        source_file=source_name
                    ))
                    stored += 1
        except Exception:
            continue

    await db.commit()

    # if stored > 0:
    #    overall_summary = report.summary()
    #    await rag_service.store_embedding("zepp_summary", None, overall_summary, db)

    return {"filename": source_name, "metrics_extracted": len(report.daily_summaries()), "stored": stored}
