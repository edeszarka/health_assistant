"""Tests for baseline risk-score computation and persistence."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.risk_score_service import compute_baseline_scores

_TODAY = date(2026, 10, 1)
_NOW = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def _profile(**overrides) -> SimpleNamespace:
    """Build a profile-like object with sensible healthy defaults."""
    base = dict(
        age=50,
        sex="male",
        height_cm=175,
        smoking=False,
        bp_medication_ever=False,
        bp_medication_current=False,
        high_glucose_history=False,
        diabetes_diagnosed=False,
        vegetables_daily=True,
        physically_active=True,
        family_diabetes="none",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _score(value, category) -> SimpleNamespace:
    return SimpleNamespace(score_value=value, risk_category=category)


def _result(row: Optional[tuple]) -> MagicMock:
    result = MagicMock()
    result.fetchone.return_value = row
    return result


def _literal(sql: str, column: str) -> Optional[str]:
    match = re.search(rf"{column} = '([^']+)'", sql)
    return match.group(1) if match else None


def _db(
    labs: Optional[dict[str, tuple]] = None,
    systolic: Optional[int] = 120,
    metrics: Optional[dict[str, float]] = None,
    latest_scores: Optional[dict[str, Any]] = None,
) -> AsyncMock:
    """A session that answers each query by table and filter, not by order.

    Args:
        labs: ``{test_name: (value, unit)}``; default: mmol/L TC and HDL.
        systolic: Latest systolic BP, or ``None`` for no reading.
        metrics: ``{metric_type: value}``; default: weight and waist present.
        latest_scores: ``{score_type: RiskScore-like}`` already persisted.
    """
    labs = {
        "total_cholesterol": (5.2, "mmol/L"),
        "hdl_cholesterol": (1.3, "mmol/L"),
    } if labs is None else labs
    metrics = {"weight_kg": 70.0, "waist_cm": 90.0} if metrics is None else metrics
    latest_scores = latest_scores or {}

    async def execute(stmt):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "FROM lab_results" in sql:
            lab = labs.get(_literal(sql, "lab_results.test_name"))
            return _result((lab[0], lab[1], _TODAY) if lab else None)
        if "FROM blood_pressure_readings" in sql:
            return _result((systolic, _NOW) if systolic is not None else None)
        if "FROM samsung_health_metrics" in sql:
            value = metrics.get(_literal(sql, "samsung_health_metrics.metric_type"))
            return _result((value, _NOW) if value is not None else None)
        if "FROM risk_scores" in sql:
            latest = latest_scores.get(_literal(sql, "risk_scores.score_type"))
            return _result((latest,) if latest is not None else None)
        raise AssertionError(f"unexpected query: {sql}")

    db = AsyncMock()
    db.execute.side_effect = execute
    db.add = MagicMock()
    return db


def _added(db: AsyncMock) -> list:
    return [call.args[0] for call in db.add.call_args_list]


@pytest.mark.asyncio
async def test_mmol_l_labs_produce_and_persist_framingham():
    """mmol/L lab rows are converted and a framingham RiskScore is added."""
    db = _db()

    result = await compute_baseline_scores(db, _profile())

    assert result["framingham_risk_percent"] is not None
    assert 0 < result["framingham_risk_percent"] <= 100
    assert result["framingham_category"] is not None
    assert any(row.score_type == "framingham" for row in _added(db))
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_hdl_skips_framingham_without_error():
    """Missing HDL skips Framingham and adds no framingham row."""
    db = _db(labs={"total_cholesterol": (5.2, "mmol/L")})

    result = await compute_baseline_scores(db, _profile())

    assert result["framingham_risk_percent"] is None
    assert all(row.score_type != "framingham" for row in _added(db))


@pytest.mark.asyncio
async def test_missing_unit_on_cholesterol_skips_framingham():
    """A cholesterol row with no unit must not be assumed to be mg/dL."""
    db = _db(labs={
        "total_cholesterol": (5.2, None),
        "hdl_cholesterol": (1.3, "mmol/L"),
    })

    result = await compute_baseline_scores(db, _profile())

    assert result["framingham_risk_percent"] is None
    assert all(row.score_type != "framingham" for row in _added(db))


@pytest.mark.asyncio
async def test_findrisc_computed_and_persisted_with_profile():
    """A profile with weight and waist yields a persisted FINDRISC score."""
    db = _db()

    result = await compute_baseline_scores(db, _profile())

    assert isinstance(result["findrisc_score"], int)
    assert result["findrisc_category"] is not None
    assert any(row.score_type == "findrisc" for row in _added(db))


@pytest.mark.asyncio
async def test_missing_waist_skips_findrisc():
    """Without a waist measurement FINDRISC is skipped, not under-estimated."""
    db = _db(metrics={"weight_kg": 70.0})

    result = await compute_baseline_scores(db, _profile())

    assert result["findrisc_score"] is None
    assert all(row.score_type != "findrisc" for row in _added(db))


@pytest.mark.asyncio
async def test_missing_weight_skips_findrisc():
    """Without a weight (so no BMI) FINDRISC is skipped, not under-estimated."""
    db = _db(metrics={"waist_cm": 90.0})

    result = await compute_baseline_scores(db, _profile())

    assert result["findrisc_score"] is None
    assert all(row.score_type != "findrisc" for row in _added(db))


@pytest.mark.asyncio
async def test_findrisc_uses_profile_answers():
    """Each yes/no answer and the family degree reach the FINDRISC points."""
    healthy = await compute_baseline_scores(_db(), _profile())
    risky = await compute_baseline_scores(_db(), _profile(
        physically_active=False,         # +2
        vegetables_daily=False,          # +1
        bp_medication_ever=True,         # +2
        high_glucose_history=True,       # +5
        family_diabetes="second_degree",  # +3
    ))

    assert risky["findrisc_score"] - healthy["findrisc_score"] == 13


@pytest.mark.asyncio
async def test_framingham_uses_current_medication_and_diagnosed_diabetes():
    """Framingham reads 'currently treated' and 'diagnosed diabetes' only."""
    db = _db()
    await compute_baseline_scores(db, _profile(
        bp_medication_ever=True, high_glucose_history=True,
    ))
    inputs = next(row for row in _added(db) if row.score_type == "framingham").inputs_json

    assert '"bp_treated": false' in inputs
    assert '"diabetes": false' in inputs

    db = _db()
    await compute_baseline_scores(db, _profile(
        bp_medication_ever=True, bp_medication_current=True,
        high_glucose_history=True, diabetes_diagnosed=True,
    ))
    inputs = next(row for row in _added(db) if row.score_type == "framingham").inputs_json

    assert '"bp_treated": true' in inputs
    assert '"diabetes": true' in inputs


@pytest.mark.asyncio
async def test_identical_inputs_do_not_add_second_row():
    """Re-running with unchanged values is idempotent."""
    profile = _profile()

    first_db = _db()
    first = await compute_baseline_scores(first_db, profile)
    inserted = {row.score_type: row for row in _added(first_db)}

    second_db = _db(latest_scores={
        name: _score(row.score_value, row.risk_category)
        for name, row in inserted.items()
    })
    second = await compute_baseline_scores(second_db, profile)

    second_db.add.assert_not_called()
    second_db.commit.assert_not_called()
    assert second["framingham_risk_percent"] == first["framingham_risk_percent"]


@pytest.mark.asyncio
async def test_no_profile_returns_nones_without_writes():
    """With no profile, all scores are None and no DB work happens."""
    db = AsyncMock()

    result = await compute_baseline_scores(db, None)

    assert result == {
        "framingham_risk_percent": None,
        "framingham_category": None,
        "findrisc_score": None,
        "findrisc_category": None,
    }
    db.execute.assert_not_called()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_female_profile_gets_no_framingham_score():
    """The female Framingham table is a placeholder, so no score is shown or saved."""
    db = _db()

    result = await compute_baseline_scores(db, _profile(sex="female"))

    assert result["framingham_risk_percent"] is None
    assert result["findrisc_score"] is not None
    assert all(row.score_type != "framingham" for row in _added(db))
