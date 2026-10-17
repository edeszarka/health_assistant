"""Family history router with pgvector embedding and MedlinePlus enrichment."""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import FamilyHistoryCreate, FamilyHistoryResponse
from models.db_models import Embedding, FamilyHistory
from services.embedding_text import family_history_text
from services.rag_service import rag_service
from services.medlineplus_service import medlineplus_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[FamilyHistoryResponse])
async def list_family_history(
    db: AsyncSession = Depends(get_db),
) -> list[FamilyHistory]:
    """List all family history entries.

    Args:
        db: Async DB session.
    """
    result = await db.execute(select(FamilyHistory).order_by(FamilyHistory.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=FamilyHistoryResponse, status_code=201)
async def add_family_history(
    data: FamilyHistoryCreate,
    db: AsyncSession = Depends(get_db),
) -> FamilyHistory:
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

    # MedlinePlus enrichment (fire-and-forget; errors do not fail the request)
    if data.icd10_code:
        try:
            await medlineplus_service.get_condition_info(data.icd10_code, db)
        except Exception as exc:
            logger.warning(
                "MedlinePlus lookup failed for ICD-10 code %s: %s", data.icd10_code, exc
            )

    await db.commit()
    await db.refresh(entry)
    return entry


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
