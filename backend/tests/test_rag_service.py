"""Tests for RAGService — embedding and similarity search."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.rag_service import RAGService


FAKE_EMBEDDING = [0.1] * 768  # 768-dimensional dummy vector


@pytest.fixture
def service():
    return RAGService()


@pytest.mark.asyncio
async def test_embed_text_returns_list(service):
    """embed_text should return a list of floats from Ollama."""
    fake_resp = AsyncMock()
    fake_resp.json.return_value = {"embedding": FAKE_EMBEDDING}
    fake_resp.raise_for_status = AsyncMock()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.post.return_value = fake_resp
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_http

        result = await service.embed_text("blood glucose level")

    assert isinstance(result, list)
    assert len(result) == 768


@pytest.mark.asyncio
async def test_store_embedding_adds_and_commits(service):
    """store_embedding should add one Embedding row and commit."""
    mock_db = AsyncMock()

    with patch.object(service, "embed_text", return_value=FAKE_EMBEDDING):
        await service.store_embedding("lab_result", 42, "Hemoglobin 14g/dL normal", mock_db)

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_similarity_search_returns_content(service):
    """similarity_search should execute a query and return content strings."""
    mock_db = AsyncMock()

    mock_row1 = ("Hemoglobin is a protein in red blood cells.",)
    mock_row2 = ("Glucose is a blood sugar marker.",)
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row1, mock_row2]
    mock_db.execute.return_value = mock_result

    with patch.object(service, "embed_text", return_value=FAKE_EMBEDDING):
        results = await service.similarity_search("blood test", limit=2, db=mock_db)

    assert len(results) == 2
    assert "Hemoglobin" in results[0]


@pytest.mark.asyncio
async def test_similarity_search_no_db_returns_empty(service):
    """similarity_search with db=None should return [] without error."""
    result = await service.similarity_search("anything", limit=5, db=None)
    assert result == []
