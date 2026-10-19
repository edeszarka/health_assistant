"""Tests for choosing the lab rows that go into the chat prompt (ADR 0012).

All lab values here are fictional.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from routers.chat import (
    LabRow,
    _build_lab_trends_summary,
    format_lab_selection,
    select_lab_tests,
)
from services.medlineplus_context import mentioned_keys


def _row(name: str, flagged: bool = False, rising: bool = False) -> LabRow:
    return LabRow(name, name.upper(), f"  {name} line", flagged, rising)


ROWS = [
    _row("ggt", flagged=True),
    _row("hemoglobin"),
    _row("ldl_cholesterol"),
    _row("mcv", rising=True),
    _row("total_cholesterol"),
]


def _names(rows: list[LabRow]) -> list[str]:
    return [row.test_name for row in rows]


def test_named_test_and_flagged_are_shown_rest_names_only() -> None:
    selection = select_lab_tests(ROWS, ["hemoglobin"], include_risk=False)
    assert _names(selection.asked) == ["hemoglobin"]
    assert _names(selection.flagged) == ["ggt"]
    assert selection.key == []
    assert _names(selection.names_only) == ["ldl_cholesterol", "mcv", "total_cholesterol"]


def test_hungarian_question_selects_total_cholesterol() -> None:
    selection = select_lab_tests(ROWS, mentioned_keys("Mennyi a koleszterinem?"), False)
    assert _names(selection.asked) == ["total_cholesterol"]


def test_no_test_named_shows_flagged_risk_labs_and_rising() -> None:
    selection = select_lab_tests(ROWS, [], include_risk=False)
    assert selection.asked == []
    assert _names(selection.flagged) == ["ggt"]
    assert _names(selection.key) == ["ldl_cholesterol", "mcv", "total_cholesterol"]
    assert _names(selection.names_only) == ["hemoglobin"]


def test_named_test_without_result_is_reported_missing() -> None:
    selection = select_lab_tests(ROWS, ["tsh"], include_risk=False)
    assert selection.missing == ["tsh"]
    assert "Asked about, not on record: tsh" in format_lab_selection(selection)


def test_risk_question_adds_risk_labs_to_named_test() -> None:
    selection = select_lab_tests(ROWS, ["hemoglobin"], include_risk=True)
    assert _names(selection.key) == ["ldl_cholesterol", "mcv", "total_cholesterol"]


def test_named_test_outside_relevant_list_is_still_shown() -> None:
    rows = [*ROWS, _row("vitamin_d")]
    selection = select_lab_tests(rows, ["vitamin_d"], include_risk=False)
    assert _names(selection.asked) == ["vitamin_d"]
    unnamed = select_lab_tests(rows, [], include_risk=False)
    assert "vitamin_d" not in _names(unnamed.names_only)


def _result(name: str, raw: str, value: float, day: date, flagged: bool) -> SimpleNamespace:
    return SimpleNamespace(
        test_name=name, raw_name=raw, value=value, unit="U/L", test_date=day,
        is_flagged=flagged, ref_range_low=0.0, ref_range_high=55.0,
    )


@pytest.mark.asyncio
async def test_summary_puts_asked_first_and_lists_the_rest_by_name() -> None:
    results = [
        _result("ggt", "GGT", 38.0, date(2026, 1, 5), False),
        _result("ggt", "GGT", 71.0, date(2026, 5, 12), True),
        _result("hemoglobin", "Hemoglobin", 148.0, date(2026, 5, 12), False),
        _result("mcv", "MCV", 90.0, date(2026, 5, 12), False),
    ]
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = results
    db = AsyncMock()
    db.execute.return_value = rows

    text = await _build_lab_trends_summary(db, "What is my hemoglobin?", False)

    asked = text.index("=== Asked about ===")
    flagged = text.index("=== Flagged lab values ===")
    assert asked < text.index("Hemoglobin (hemoglobin): 148.0 U/L") < flagged
    assert "  ⚠   GGT (ggt): 38.0 → 71.0 U/L (ref: 0.0–55.0 U/L)" in text
    assert "[HIGH ↑]" in text
    assert text.endswith("Other tests on record, within range (values not shown): MCV")
