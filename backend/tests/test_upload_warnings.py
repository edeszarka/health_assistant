"""Tests that /upload/pdf surfaces parser errors as response warnings."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.datastructures import UploadFile

from routers import upload
from routers.upload import upload_pdf


def _fake_file() -> UploadFile:
    return UploadFile(file=io.BytesIO(b"%PDF-1.4 fake pdf content"), filename="labs.pdf")


def _report(parse_errors: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        results=[],
        patient=SimpleNamespace(sample_date=None),
        parse_errors=parse_errors,
    )


@pytest.mark.asyncio
async def test_upload_pdf_returns_parse_errors_as_warnings(tmp_path, monkeypatch):
    """Parser errors must be surfaced to the caller, not dropped silently."""
    monkeypatch.setattr(upload, "settings", SimpleNamespace(upload_dir=str(tmp_path)))
    report = _report(["Sample date not found — no 'Mintavétel' line matched"])

    with patch.object(upload.pdf_parser, "parse", return_value=report):
        result = await upload_pdf(file=_fake_file(), db=AsyncMock())

    assert result["warnings"] == report.parse_errors


@pytest.mark.asyncio
async def test_upload_pdf_warnings_empty_when_no_errors(tmp_path, monkeypatch):
    """The response shape stays stable: an empty list, never an omitted key."""
    monkeypatch.setattr(upload, "settings", SimpleNamespace(upload_dir=str(tmp_path)))

    with patch.object(upload.pdf_parser, "parse", return_value=_report([])):
        result = await upload_pdf(file=_fake_file(), db=AsyncMock())

    assert result["warnings"] == []
