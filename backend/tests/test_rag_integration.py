"""Integration tests: similarity search against a real Postgres + pgvector.

These run only when ``RUN_DB_INTEGRATION=1`` is set. CI sets it and provides a
throwaway pgvector service; local runs skip, so they can never drop or fill the
``embeddings`` table of a real database. Embeddings are hand-made vectors and
``embed_text`` is patched, so no Ollama is needed.
"""
from __future__ import annotations

import math
import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config import settings
from models.db_models import Embedding
from services.rag_service import RAGService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_DB_INTEGRATION") != "1",
        reason="needs a throwaway Postgres + pgvector (set RUN_DB_INTEGRATION=1)",
    ),
]

DIM = 768


def _vector(**components: float) -> list[float]:
    """A unit vector with the given non-zero components, e.g. _vector(x0=0.8, x1=0.6)."""
    vec = [0.0] * DIM
    for key, value in components.items():
        vec[int(key[1:])] = value
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


QUERY = _vector(x0=1.0)
ROWS = [
    # (content, source_type, vector, cosine similarity to QUERY)
    ("exact match", "lab_result", _vector(x0=1.0), 1.0),
    ("close match", "lab_result", _vector(x0=0.8, x1=0.6), 0.8),
    ("unrelated", "family_history", _vector(x1=1.0), 0.0),
]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Embedding.__table__.drop, checkfirst=True)
        await conn.run_sync(Embedding.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            Embedding(source_type=source_type, source_id=i, content=content, embedding=vec)
            for i, (content, source_type, vec, _) in enumerate(ROWS)
        )
        await session.commit()
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Embedding.__table__.drop, checkfirst=True)
    await engine.dispose()


async def _search(db: AsyncSession, **kwargs) -> list[str]:
    service = RAGService()
    with patch.object(service, "embed_text", AsyncMock(return_value=QUERY)):
        return await service.similarity_search("query", db=db, **kwargs)


@pytest.mark.asyncio
async def test_results_are_ordered_by_similarity(db):
    assert await _search(db, threshold=0.0) == ["exact match", "close match", "unrelated"]


@pytest.mark.asyncio
async def test_threshold_drops_less_similar_rows(db):
    assert await _search(db, threshold=0.9) == ["exact match"]
    assert await _search(db, threshold=0.7) == ["exact match", "close match"]


@pytest.mark.asyncio
async def test_source_types_filter_restricts_rows(db):
    assert await _search(db, threshold=0.0, source_types=["family_history"]) == ["unrelated"]


@pytest.mark.asyncio
async def test_limit_is_applied(db):
    assert await _search(db, threshold=0.0, limit=1) == ["exact match"]
