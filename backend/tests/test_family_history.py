"""Tests for the family history router: MedlinePlus scope and embedding cleanup."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.api_models import FamilyHistoryCreate
from routers import family_history
from models.db_models import FamilyHistory
from routers.family_history import (
    add_family_history,
    delete_family_history,
    list_family_history,
)

E11_INFO = {
    "title": "Diabetes Type 2",
    "summary": "Type 2 diabetes is a disease in which blood sugar is too high.",
    "url": "https://medlineplus.gov/diabetestype2.html",
}


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()

    async def refresh(entry):
        # A real refresh loads the server-generated columns.
        entry.id = 1
        entry.created_at = datetime(2026, 10, 19, tzinfo=timezone.utc)

    db.refresh.side_effect = refresh
    return db


def _compiled(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_free_text_condition_is_not_sent_to_medlineplus():
    """Without an ICD-10 code, nothing is sent to MedlinePlus."""
    data = FamilyHistoryCreate(relation="father", condition="rare private condition")
    with patch.object(family_history.rag_service, "store_embedding", AsyncMock()), \
         patch.object(family_history.medlineplus_service, "search_health_topic", AsyncMock()) as search, \
         patch.object(family_history.medlineplus_service, "get_condition_info", AsyncMock()) as connect:
        await add_family_history(data=data, db=_db())

    search.assert_not_called()
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_icd10_code_is_looked_up_on_medlineplus():
    """With an ICD-10 code, only the code is sent."""
    data = FamilyHistoryCreate(relation="mother", condition="diabetes", icd10_code="E11")
    with patch.object(family_history.rag_service, "store_embedding", AsyncMock()), \
         patch.object(family_history.medlineplus_service, "search_health_topic", AsyncMock()) as search, \
         patch.object(family_history.medlineplus_service, "get_condition_info", AsyncMock(return_value=E11_INFO)) as connect:
        response = await add_family_history(data=data, db=_db())

    connect.assert_awaited_once()
    assert connect.await_args.args[0] == "E11"
    search.assert_not_called()
    assert response.medlineplus.url == E11_INFO["url"]


@pytest.mark.asyncio
async def test_list_returns_cached_medlineplus_info_without_network():
    """Listing reads MedlinePlus from the cache only and attaches it per entry."""
    with_code = FamilyHistory(id=1, relation="mother", condition="diabetes", icd10_code="E11",
                              created_at=datetime(2026, 10, 19, tzinfo=timezone.utc))
    without_code = FamilyHistory(id=2, relation="father", condition="asthma",
                                 created_at=datetime(2026, 10, 19, tzinfo=timezone.utc))
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [with_code, without_code]
    db = _db()
    db.execute = AsyncMock(return_value=rows)
    with patch.object(family_history.medlineplus_service, "get_cached",
                      AsyncMock(return_value=E11_INFO)) as cached,          patch.object(family_history.medlineplus_service, "get_condition_info", AsyncMock()) as fetch:
        responses = await list_family_history(db=db)

    fetch.assert_not_called()
    cached.assert_awaited_once()
    assert cached.await_args.args[0] == "icd10:E11"
    assert responses[0].medlineplus.title == "Diabetes Type 2"
    assert responses[1].medlineplus is None


@pytest.mark.asyncio
async def test_medlineplus_failure_is_logged_not_raised(caplog):
    """A MedlinePlus failure must not fail the request and must be logged."""
    data = FamilyHistoryCreate(relation="mother", condition="diabetes", icd10_code="E11")
    failing = AsyncMock(side_effect=RuntimeError("network down"))
    with patch.object(family_history.rag_service, "store_embedding", AsyncMock()), \
         patch.object(family_history.medlineplus_service, "get_condition_info", failing), \
         caplog.at_level(logging.WARNING, logger="routers.family_history"):
        await add_family_history(data=data, db=_db())

    assert "MedlinePlus lookup failed" in caplog.text


@pytest.mark.asyncio
async def test_delete_also_removes_the_entry_embedding():
    """Deleting an entry must delete its family_history embedding as well."""
    entry = MagicMock()
    found = MagicMock()
    found.scalar_one_or_none.return_value = entry
    db = _db()
    db.execute = AsyncMock(side_effect=[found, MagicMock()])

    await delete_family_history(entry_id=7, db=db)

    delete_sql = _compiled(db.execute.await_args_list[1].args[0])
    assert delete_sql.startswith("DELETE FROM embeddings")
    assert "embeddings.source_type = 'family_history'" in delete_sql
    assert "embeddings.source_id = 7" in delete_sql
    db.delete.assert_awaited_once_with(entry)
    db.commit.assert_awaited_once()
