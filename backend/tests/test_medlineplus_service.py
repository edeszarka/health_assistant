"""Tests for MedlinePlusService — cache logic."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.medlineplus_service import MedlinePlusService


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document url="https://medlineplus.gov/highbloodpressure.html">
      <content name="title">High Blood Pressure</content>
      <content name="snippet">High blood pressure raises the risk of heart attack.</content>
    </document>
  </list>
</nlmSearchResult>"""


@pytest.fixture
def service():
    return MedlinePlusService()


@pytest.mark.asyncio
async def test_cache_miss_then_hit(service):
    """First call fetches from API and caches; second call uses cache."""
    mock_db = AsyncMock()

    # Simulate cache miss (no row found)
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = empty_result

    fake_http_response = AsyncMock()
    fake_http_response.text = SAMPLE_XML
    fake_http_response.raise_for_status = AsyncMock()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.get.return_value = fake_http_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_http

        result = await service.search_health_topic("high blood pressure", mock_db)

    assert "title" in result
    # Verify commit was called (cache was saved)
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cache_hit_returns_without_http(service):
    """If cache row exists and not expired, no HTTP call is made."""
    mock_db = AsyncMock()

    cached_data = {"title": "Cached Title", "summary": "Cached summary", "url": "http://example.com", "specialist": None}
    cache_row = MagicMock()
    cache_row.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    cache_row.response_json = json.dumps(cached_data)

    hit_result = MagicMock()
    hit_result.scalar_one_or_none.return_value = cache_row
    mock_db.execute.return_value = hit_result

    with patch("httpx.AsyncClient") as mock_cls:
        result = await service.search_health_topic("high blood pressure", mock_db)
        mock_cls.assert_not_called()  # No HTTP call made

    assert result["title"] == "Cached Title"
