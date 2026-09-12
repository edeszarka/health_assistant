"""Tests that lab PDF uploads do not persist the raw original filename."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.datastructures import UploadFile

from routers import upload
from routers.upload import upload_pdf


ORIGINAL_FILENAME = "Kovacs_Anna_labs.pdf"


def _fake_report() -> SimpleNamespace:
    """Minimal ParsedLabReport stand-in with one flagged lab value."""
    return SimpleNamespace(
        results=[
            SimpleNamespace(
                normalized_name="ldl_cholesterol",
                raw_name="LDL",
                value=4.2,
                unit="mmol/L",
                ref_range_low=0.0,
                ref_range_high=3.4,
                is_flagged=True,
            )
        ],
        patient=SimpleNamespace(sample_date=None),
    )


@pytest.mark.asyncio
async def test_upload_pdf_does_not_persist_original_filename(tmp_path, monkeypatch):
    """source_filename and the on-disk file must not embed the original name."""
    monkeypatch.setattr(
        upload, "settings", SimpleNamespace(upload_dir=str(tmp_path))
    )

    fake_file = UploadFile(
        file=io.BytesIO(b"%PDF-1.4 fake pdf content"),
        filename=ORIGINAL_FILENAME,
    )
    mock_db = AsyncMock()

    with patch.object(
        upload.pdf_parser, "parse", return_value=_fake_report()
    ), patch.object(upload.rag_service, "store_embedding", new=AsyncMock()):
        result = await upload_pdf(file=fake_file, db=mock_db)

    # The user-facing response still exposes the original filename.
    assert result["filename"] == ORIGINAL_FILENAME

    # The persisted DB row must carry a sanitized identifier instead.
    persisted_row = mock_db.add.call_args.args[0]
    assert persisted_row.source_filename != ORIGINAL_FILENAME
    assert "Kovacs" not in persisted_row.source_filename

    # The file written to disk must not be named after the original filename.
    saved_names = [path.name for path in tmp_path.iterdir()]
    assert saved_names
    assert all(ORIGINAL_FILENAME not in name for name in saved_names)
    assert all("Kovacs" not in name for name in saved_names)
