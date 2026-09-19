"""Tests for baseline risk-score computation and persistence."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.risk_score_service import compute_baseline_scores


def _profile(**overrides) -> SimpleNamespace:
    """Build a profile-like object with sensible healthy defaults."""
    base = dict(
        age=50,
        sex="male",
        height_cm=175,
        waist_cm=90,
        smoking=False,
        bp_medication=False,
        high_glucose_history=False,
        vegetables_daily=True,
        family_diabetes=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _row(value) -> MagicMock:
    """A mock execute result whose fetchone returns ``value``."""
    result = MagicMock()
    result.fetchone.return_value = value
    return result


def _score(value, category) -> SimpleNamespace:
    return SimpleNamespace(score_value=value, risk_category=category)


def _mock_db(results: list) -> AsyncMock:
    db = AsyncMock()
    db.execute.side_effect = results
    return db


def _happy_path_results(latest_framingham=None, latest_findrisc=None) -> list:
    """Execute results for: TC, HDL, systolic, weight, framingham, findrisc."""
    return [
        _row((5.2, "mmol/L")),   # total cholesterol
        _row((1.3, "mmol/L")),   # HDL cholesterol
        _row((120,)),            # systolic
        _row((70.0,)),           # weight
        _row(latest_framingham),  # latest framingham row
        _row(latest_findrisc),   # latest findrisc row
    ]


@pytest.mark.asyncio
async def test_mmol_l_labs_produce_and_persist_framingham():
    """mmol/L lab rows are converted and a framingham RiskScore is added."""
    db = _mock_db(_happy_path_results())

    result = await compute_baseline_scores(db, _profile())

    assert result["framingham_risk_percent"] is not None
    assert 0 < result["framingham_risk_percent"] <= 100
    assert result["framingham_category"] is not None

    added = [call.args[0] for call in db.add.call_args_list]
    assert any(row.score_type == "framingham" for row in added)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_hdl_skips_framingham_without_error():
    """Missing HDL skips Framingham and adds no framingham row."""
    db = _mock_db([
        _row((5.2, "mmol/L")),  # total cholesterol present
        _row(None),             # hdl_cholesterol absent
        _row(None),             # hdl fallback absent
        _row((120,)),           # systolic
        _row((70.0,)),          # weight
        _row(None),             # latest findrisc
    ])

    result = await compute_baseline_scores(db, _profile())

    assert result["framingham_risk_percent"] is None
    added = [call.args[0] for call in db.add.call_args_list]
    assert all(row.score_type != "framingham" for row in added)


@pytest.mark.asyncio
async def test_missing_unit_on_cholesterol_skips_framingham():
    """A cholesterol row with no unit must not be assumed to be mg/dL."""
    db = _mock_db([
        _row((5.2, None)),      # unit is None → conversion refused
        _row((1.3, "mmol/L")),  # HDL
        _row((120,)),           # systolic
        _row((70.0,)),          # weight
        _row(None),             # latest findrisc
    ])

    result = await compute_baseline_scores(db, _profile())

    assert result["framingham_risk_percent"] is None
    added = [call.args[0] for call in db.add.call_args_list]
    assert all(row.score_type != "framingham" for row in added)


@pytest.mark.asyncio
async def test_findrisc_computed_and_persisted_with_profile():
    """A profile yields a persisted FINDRISC score."""
    db = _mock_db(_happy_path_results())

    result = await compute_baseline_scores(db, _profile())

    assert isinstance(result["findrisc_score"], int)
    assert result["findrisc_category"] is not None
    added = [call.args[0] for call in db.add.call_args_list]
    assert any(row.score_type == "findrisc" for row in added)


@pytest.mark.asyncio
async def test_identical_inputs_do_not_add_second_row():
    """Re-running with unchanged values is idempotent."""
    profile = _profile()

    first_db = _mock_db(_happy_path_results())
    first = await compute_baseline_scores(first_db, profile)
    inserted = {call.args[0].score_type: call.args[0] for call in first_db.add.call_args_list}

    second_db = _mock_db(_happy_path_results(
        latest_framingham=(_score(
            inserted["framingham"].score_value, inserted["framingham"].risk_category
        ),),
        latest_findrisc=(_score(
            inserted["findrisc"].score_value, inserted["findrisc"].risk_category
        ),),
    ))

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
