"""Rebuild every stored RAG embedding with the current texts and task prefix.

Run inside the backend container after changing the embedding templates
(services/embedding_text.py), the task prefixes or the embedding model:

    python -m scripts.reembed

Lab and family-history texts are rebuilt from their source rows; other
source types keep their stored text and are only re-embedded. Rows whose
source record no longer exists are left untouched and counted. Safe to run
repeatedly. Prints counts only, never content.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import AsyncSessionLocal
from models.db_models import Embedding, FamilyHistory, LabResult
from services.embedding_text import family_history_text, lab_result_text
from services.rag_service import rag_service


async def _lab_text(db: AsyncSession, source_id: Optional[int]) -> Optional[str]:
    row = await db.get(LabResult, source_id) if source_id is not None else None
    if row is None:
        return None
    return lab_result_text(row.raw_name, row.test_name, row.value, row.unit, row.is_flagged)


async def _family_text(db: AsyncSession, source_id: Optional[int]) -> Optional[str]:
    row = await db.get(FamilyHistory, source_id) if source_id is not None else None
    if row is None:
        return None
    return family_history_text(row.relation, row.condition, row.age_of_onset)


async def _new_text(db: AsyncSession, emb: Embedding) -> Optional[str]:
    """Text to embed for one row, or ``None`` when its source record is gone."""
    if emb.source_type == "lab_result":
        return await _lab_text(db, emb.source_id)
    if emb.source_type == "family_history":
        return await _family_text(db, emb.source_id)
    return emb.content


async def reembed_all() -> Counter:
    """Re-embed every row in one transaction and return per-type counts."""
    counts: Counter = Counter()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Embedding))).scalars().all()
        for emb in rows:
            text = await _new_text(db, emb)
            if text is None:
                counts[f"{emb.source_type}: orphaned, skipped"] += 1
                continue
            emb.content = text
            emb.embedding = await rag_service.embed_text(text, task="document")
            counts[f"{emb.source_type}: re-embedded"] += 1
        await db.commit()
    return counts


if __name__ == "__main__":
    for key, value in sorted(asyncio.run(reembed_all()).items()):
        print(f"{key}: {value}")
