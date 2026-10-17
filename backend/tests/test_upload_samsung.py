"""Tests for POST /upload/samsung: no client filename reaches disk or the DB."""
from __future__ import annotations

import csv
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from starlette.datastructures import UploadFile

from routers import upload
from routers.upload import upload_samsung

ACCOUNT_FILENAME = "samsunghealth_some.account_20260226101817.zip"


def _export_zip() -> bytes:
    rows = io.StringIO()
    writer = csv.DictWriter(rows, fieldnames=["day_time", "count", "distance", "calorie"])
    writer.writeheader()
    writer.writerow({"day_time": "2026-01-15 00:00:00.000", "count": "8000", "distance": "6000", "calorie": "300"})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("jsons/../step_daily_trend_20260115.csv", rows.getvalue())
    return buf.getvalue()


def _file(name: str, content: bytes | None = None) -> UploadFile:
    return UploadFile(file=io.BytesIO(content if content is not None else _export_zip()), filename=name)


def _db() -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    return db


def _source_files(db: AsyncMock) -> set[str]:
    values = set()
    for call in db.execute.await_args_list:
        params = call.args[0].compile(dialect=postgresql.dialect()).params
        values.add(params["source_file"])
    return values


@pytest.mark.asyncio
async def test_traversal_filename_writes_nothing_to_disk(tmp_path, monkeypatch):
    """A '../' filename must not create any file, inside or outside upload_dir."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(upload, "settings", SimpleNamespace(upload_dir=str(upload_dir)))
    before = set(tmp_path.rglob("*"))

    with patch.object(upload.rag_service, "store_embedding", AsyncMock()):
        result = await upload_samsung(files=[_file("../../escaped.zip")], db=_db())

    assert result["stored"] > 0
    assert set(tmp_path.rglob("*")) == before


@pytest.mark.asyncio
async def test_original_filename_is_not_persisted():
    """The DB gets a generated id, never the export name (it carries the account name)."""
    db = _db()
    with patch.object(upload.rag_service, "store_embedding", AsyncMock()):
        result = await upload_samsung(files=[_file(ACCOUNT_FILENAME)], db=db)

    assert result["filename"] == ACCOUNT_FILENAME  # shown back to the user only
    [source_file] = _source_files(db)
    assert source_file.startswith("samsung_")
    assert "account" not in source_file and ACCOUNT_FILENAME not in source_file


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "files",
    [
        [],
        ["steps.csv"],
        ["export.zip", "export2.zip"],
    ],
)
async def test_anything_but_one_zip_is_rejected(files):
    with pytest.raises(HTTPException) as excinfo:
        await upload_samsung(files=[_file(n) for n in files], db=_db())
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_corrupt_zip_returns_422():
    with pytest.raises(HTTPException) as excinfo:
        await upload_samsung(files=[_file("export.zip", b"not a zip")], db=_db())
    assert excinfo.value.status_code == 422
