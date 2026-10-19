"""Family history router with pgvector embedding and MedlinePlus enrichment."""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import FamilyHistoryCreate, FamilyHistoryResponse, MedlinePlusInfo
from models.db_models import Embedding, FamilyHistory
from services.embedding_text import family_history_text
from services.rag_service import rag_service
from services.medlineplus_service import (
    ICD10_CM_SYSTEM,
    connect_cache_key,
    medlineplus_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _info(data: Optional[dict]) -> Optional[MedlinePlusInfo]:
    """Turn a MedlinePlus result into API info; ``None`` if it has no page."""
    if not data or not data.get("url") or not data.get("summary"):
        return None
    return MedlinePlusInfo(
        title=data.get("title") or "", summary=data["summary"], url=data["url"]
    )


def _response(entry: FamilyHistory, info: Optional[MedlinePlusInfo]) -> FamilyHistoryResponse:
    """Build the API response for one entry with its MedlinePlus info."""
    response = FamilyHistoryResponse.model_validate(entry)
    response.medlineplus = info
    return response


@router.get("/", response_model=List[FamilyHistoryResponse])
async def list_family_history(
    db: AsyncSession = Depends(get_db),
) -> list[FamilyHistoryResponse]:
    """List all family history entries with their cached MedlinePlus info.

    MedlinePlus is read from the cache only; listing sends no request.

    Args:
        db: Async DB session.
    """
    result = await db.execute(select(FamilyHistory).order_by(FamilyHistory.created_at.desc()))
    responses = []
    for entry in result.scalars().all():
        info = None
        if entry.icd10_code:
            key = connect_cache_key(str(entry.icd10_code), ICD10_CM_SYSTEM)
            info = _info(await medlineplus_service.get_cached(key, db))
        responses.append(_response(entry, info))
    return responses


@router.post("/", response_model=FamilyHistoryResponse, status_code=201)
async def add_family_history(
    data: FamilyHistoryCreate,
    db: AsyncSession = Depends(get_db),
) -> FamilyHistoryResponse:
    """Add a family history entry, embed it, and look up its ICD-10 code on MedlinePlus.

    Only a user-supplied ICD-10 code is sent to MedlinePlus; the free-text
    condition never leaves the host.

    Args:
        data: FamilyHistoryCreate payload.
        db: Async DB session.
    """
    entry = FamilyHistory(
        relation=data.relation,
        condition=data.condition,
        icd10_code=data.icd10_code,
        age_of_onset=data.age_of_onset,
        notes=data.notes,
    )
    db.add(entry)
    await db.flush()

    # Embed
    embed_text = family_history_text(data.relation, data.condition, data.age_of_onset)
    await rag_service.store_embedding("family_history", entry.id, embed_text, db)

    # MedlinePlus enrichment (errors do not fail the request)
    info = None
    if data.icd10_code:
        try:
            info = _info(await medlineplus_service.get_condition_info(data.icd10_code, db))
        except Exception as exc:
            logger.warning(
                "MedlinePlus lookup failed for ICD-10 code %s: %s", data.icd10_code, exc
            )

    await db.commit()
    await db.refresh(entry)
    return _response(entry, info)


@router.delete("/{entry_id}", status_code=204)
async def delete_family_history(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a family history entry by ID, together with its embedding.

    The embedding must go too, otherwise chat retrieval would keep returning
    the deleted entry.

    Args:
        entry_id: The ID of the entry to delete.
        db: Async DB session.
    """
    result = await db.execute(select(FamilyHistory).where(FamilyHistory.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    await db.execute(
        delete(Embedding).where(
            Embedding.source_type == "family_history",
            Embedding.source_id == entry_id,
        )
    )
    await db.delete(entry)
    await db.commit()
