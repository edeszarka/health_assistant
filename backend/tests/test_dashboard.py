"""Tests for the dashboard summary: which lab flags and risk scores are shown."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.db_models import LabResult, RiskScore, UserProfile
from routers import dashboard

MALE_PROFILE = SimpleNamespace(sex="male", diabetes_diagnosed=False, age=50)


def _lab(
    index: int, name: str, flagged: bool = False, test_date: date = date(2026, 1, 1)
) -> SimpleNamespace:
    """A lab row; a higher index was stored more recently."""
    return SimpleNamespace(
        id=index, test_name=name, raw_name=name, value=float(index), unit="mmol/L",
        ref_range_low=None, ref_range_high=None, is_flagged=flagged, test_date=test_date,
        source_filename="upload",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
    )


def _score(score_type: str, value: float = 1.0, category: str = "Low") -> SimpleNamespace:
    return SimpleNamespace(score_type=score_type, score_value=value, risk_category=category)


def _fake_db(
    labs: list[SimpleNamespace], scores: list[SimpleNamespace], profile: Any = MALE_PROFILE
) -> AsyncMock:
    """A session returning rows newest first and honouring the statement's LIMIT."""
    newest_labs = sorted(labs, key=lambda lab: lab.created_at, reverse=True)
    rows = {LabResult: newest_labs, RiskScore: scores, UserProfile: [profile] if profile else []}

    async def execute(stmt: Any) -> MagicMock:
        found = rows[stmt.column_descriptions[0]["entity"]]
        limit: Optional[Any] = stmt._limit_clause
        if limit is not None:
            found = found[: limit.value]
        result = MagicMock()
        result.scalars.return_value.all.return_value = found
        result.scalar_one_or_none.return_value = found[0] if found else None
        return result

    db = AsyncMock()
    db.execute.side_effect = execute
    return db


async def _summary(db: AsyncMock) -> Any:
    with patch.object(dashboard, "bp_summary", AsyncMock(return_value=None)):
        return await dashboard.get_dashboard_summary(db=db)


@pytest.mark.asyncio
async def test_flag_outside_the_ten_newest_rows_is_shown():
    """A flagged value must not vanish because ten other rows were stored later."""
    labs = [_lab(0, "ldl_cholesterol", flagged=True)]
    labs += [_lab(i, f"test_{i}") for i in range(1, 12)]

    summary = await _summary(_fake_db(labs, []))

    assert len(summary.active_flags) == 1
    assert summary.active_flags[0].startswith("ldl_cholesterol:")


@pytest.mark.asyncio
async def test_old_flag_is_not_shown_when_the_latest_result_is_normal():
    labs = [
        _lab(1, "glucose", flagged=False, test_date=date(2026, 2, 1)),
        _lab(2, "glucose", flagged=True, test_date=date(2025, 2, 1)),  # older test, stored later
    ]

    summary = await _summary(_fake_db(labs, []))

    assert summary.active_flags == []


@pytest.mark.asyncio
async def test_flag_of_the_latest_result_is_shown_once():
    labs = [
        _lab(1, "glucose", flagged=True, test_date=date(2025, 2, 1)),
        _lab(2, "glucose", flagged=True, test_date=date(2026, 2, 1)),
    ]

    summary = await _summary(_fake_db(labs, []))

    assert summary.active_flags == ["glucose: 2.0 mmol/L"]


@pytest.mark.asyncio
async def test_latest_labs_stay_the_ten_newest_rows():
    labs = [_lab(i, f"test_{i}") for i in range(15)]

    summary = await _summary(_fake_db(labs, []))

    assert [lab.id for lab in summary.latest_labs] == list(range(14, 4, -1))


@pytest.mark.asyncio
async def test_blood_pressure_rows_do_not_push_out_the_risk_scores():
    """Five newer BP readings must not hide the risk scores."""
    scores = [_score("bp_classification") for _ in range(5)]
    scores += [_score("framingham", 8.0), _score("findrisc", 7.0)]

    summary = await _summary(_fake_db([], scores))

    assert [s["score_type"] for s in summary.risk_scores] == ["framingham", "findrisc"]


@pytest.mark.asyncio
async def test_only_the_newest_score_of_each_type_is_shown():
    scores = [_score("findrisc", 9.0), _score("findrisc", 7.0)]

    summary = await _summary(_fake_db([], scores))

    assert [s["score_value"] for s in summary.risk_scores] == [9.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [
    SimpleNamespace(sex="female", diabetes_diagnosed=False, age=50),
    SimpleNamespace(sex="male", diabetes_diagnosed=True, age=50),
    SimpleNamespace(sex="male", diabetes_diagnosed=False, age=85),
    None,
], ids=["female", "diabetes", "age", "no_profile"])
async def test_saved_framingham_is_hidden_when_it_no_longer_applies(profile):
    """An older saved score stays in the table but must not be shown (Invariant 8)."""
    scores = [_score("framingham", 8.0), _score("findrisc", 7.0)]

    summary = await _summary(_fake_db([], scores, profile))

    assert [s["score_type"] for s in summary.risk_scores] == ["findrisc"]
