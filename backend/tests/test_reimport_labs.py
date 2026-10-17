"""Tests for scripts.reimport_labs (mocked session and parser)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from ingestion.pdf_parser import PDFParser
from scripts import reimport_labs
from scripts.reimport_labs import reimport

OLD_DUP, NEW_DUP, MISSING = "20260919082526_a", "20260920074452_b", "20260919075129_c"
ROWS = {
    OLD_DUP: [(1, "Azonosító"), (2, "Cím")],
    NEW_DUP: [(3, "Koleszterin"), (4, "Glükóz")],
    MISSING: [(5, "Beutaló"), (6, "Kálium")],
}


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class FakeDb:
    """Answers the script's SELECTs from ROWS and records every DELETE."""

    def __init__(self) -> None:
        self.deletes: list[str] = []
        self.commit = AsyncMock()

    async def execute(self, stmt):
        sql = _sql(stmt)
        result = MagicMock()
        if sql.startswith("DELETE"):
            self.deletes.append(sql)
        elif "DISTINCT" in sql:
            result.scalars.return_value.all.return_value = list(ROWS)
        else:
            upload_id = next(uid for uid in ROWS if uid in sql)
            result.all.return_value = ROWS[upload_id]
        return result


def _upload_dir(tmp_path):
    # The two duplicates hold identical bytes; MISSING has no file.
    for uid in (OLD_DUP, NEW_DUP):
        (tmp_path / f"{uid}.pdf").write_bytes(b"%PDF same report")
    return tmp_path


def _parser() -> MagicMock:
    parser = MagicMock()
    parser._HEADER_NAME_RE = PDFParser._HEADER_NAME_RE
    parser.parse.return_value = SimpleNamespace(
        results=[SimpleNamespace(value=1.0)] * 41, parse_errors=[]
    )
    return parser


def _by_id(outcomes):
    return {o.upload_id: o for o in outcomes}


@pytest.mark.asyncio
async def test_dry_run_plans_actions_and_writes_nothing(tmp_path):
    db = FakeDb()
    with patch.object(reimport_labs, "store_lab_results", AsyncMock()) as store:
        out = _by_id(await reimport(db, _upload_dir(tmp_path), _parser(), apply=False))

    assert out[OLD_DUP].status.startswith("duplicate of 20260920074452")
    assert out[OLD_DUP].removed == 2
    assert out[NEW_DUP].status == "re-import" and out[NEW_DUP].new_rows == 41
    assert out[MISSING].status.startswith("pdf missing")
    assert (out[MISSING].old_header_like, out[MISSING].removed) == (1, 1)
    assert db.deletes == []
    db.commit.assert_not_awaited()
    store.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_removes_duplicates_reimports_newest_and_drops_header_rows(tmp_path):
    db = FakeDb()
    store = AsyncMock(return_value=41)
    with patch.object(reimport_labs, "store_lab_results", store):
        out = _by_id(await reimport(db, _upload_dir(tmp_path), _parser(), apply=True))

    lab_deletes = [d for d in db.deletes if d.startswith("DELETE FROM lab_results")]
    assert any("IN (1, 2)" in d for d in lab_deletes)  # older duplicate: all rows
    assert any("IN (3, 4)" in d for d in lab_deletes)  # newest: replaced
    assert any("IN (5)" in d for d in lab_deletes)     # missing PDF: header row only
    assert not any("6" in d.split("IN")[-1] for d in lab_deletes)  # "Kálium" kept
    emb_deletes = [d for d in db.deletes if d.startswith("DELETE FROM embeddings")]
    assert len(emb_deletes) == 3 and all("'lab_result'" in d for d in emb_deletes)
    store.assert_awaited_once()
    assert store.await_args.args[1] == NEW_DUP
    assert out[NEW_DUP].stored == 41


@pytest.mark.asyncio
async def test_parse_failure_changes_nothing_for_that_upload(tmp_path):
    db = FakeDb()
    parser = _parser()
    parser.parse.side_effect = RuntimeError("broken pdf")
    with patch.object(reimport_labs, "store_lab_results", AsyncMock()) as store:
        out = _by_id(await reimport(db, _upload_dir(tmp_path), parser, apply=True))

    assert out[NEW_DUP].status == "parse failed: kept"
    assert not any("IN (3, 4)" in d for d in db.deletes)
    store.assert_not_awaited()
