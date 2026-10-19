"""Tests for unit handling in the hypothetical Framingham fallback."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers.chat import _build_risk_scores


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
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


def _scalar(value) -> MagicMock:
    """An execute result for queries read via scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _row(value) -> MagicMock:
    """An execute result for queries read via fetchone()."""
    result = MagicMock()
    result.fetchone.return_value = value
    return result


@pytest.mark.asyncio
async def test_hypothetical_framingham_converts_mmol_l_fallback():
    """An mmol/L stored lab is converted, not silently dropped by the guard."""
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar(None),          # _get_latest_weight
        _row((5.2, "mmol/L")),  # total_cholesterol fallback
        _row((1.3, "mmol/L")),  # hdl_cholesterol fallback
    ]

    with patch(
        "routers.chat.compute_baseline_scores", new=AsyncMock(return_value={})
    ):
        scores = await _build_risk_scores(
            db, _profile(), "what if my systolic is 150"
        )

    line = scores.get("framingham_hypothetical")
    assert line is not None
    assert "% 10-yr CV risk" in line


@pytest.mark.asyncio
async def test_hypothetical_framingham_reports_unconvertible_unit():
    """A lab row with no unit yields an explicit message, never a silent no-op."""
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar(None),          # _get_latest_weight
        _row((5.2, None)),      # total_cholesterol with no stored unit
        _row((1.3, "mmol/L")),  # hdl_cholesterol fallback
    ]

    with patch(
        "routers.chat.compute_baseline_scores", new=AsyncMock(return_value={})
    ):
        scores = await _build_risk_scores(
            db, _profile(), "what if my systolic is 150"
        )

    line = scores.get("framingham_hypothetical")
    assert line is not None
    assert "Cannot recalculate" in line
    assert "mg/dL" in line


@pytest.mark.asyncio
async def test_hypothetical_scores_are_never_persisted():
    """Invariant: hypothetical recalculations stay in memory, nothing is written."""
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [_scalar(None)]  # _get_latest_weight only

    with patch(
        "routers.chat.compute_baseline_scores", new=AsyncMock(return_value={})
    ):
        scores = await _build_risk_scores(
            db,
            _profile(),
            "what if my total cholesterol is 200 and hdl is 50 and systolic is 140",
        )

    assert "% 10-yr CV risk" in scores.get("framingham_hypothetical", "")
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_hypothetical_framingham_withheld_for_female_profile():
    """A female profile gets an explicit 'not available', never a placeholder score."""
    db = AsyncMock()
    db.execute.side_effect = [_scalar(None)]  # _get_latest_weight only

    profile = _profile()
    profile.sex = "female"
    with patch(
        "routers.chat.compute_baseline_scores", new=AsyncMock(return_value={})
    ):
        scores = await _build_risk_scores(db, profile, "what if my systolic is 150")

    line = scores.get("framingham_hypothetical", "")
    assert line.startswith("Not available")
    assert "% 10-yr CV risk" not in line


@pytest.mark.asyncio
async def test_hypothetical_findrisc_without_waist_reports_missing():
    """A 'what if' weight with no stored waist names the gap instead of a low score."""
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar(None),  # _get_latest_weight
        _row(None),     # latest waist measurement
    ]

    with patch(
        "routers.chat.compute_baseline_scores", new=AsyncMock(return_value={})
    ):
        scores = await _build_risk_scores(db, _profile(), "what if i weighed 80 kg")

    line = scores.get("findrisc_hypothetical", "")
    assert line.startswith("Cannot recalculate")
    assert "waist_cm" in line


@pytest.mark.asyncio
async def test_hypothetical_findrisc_uses_stored_waist():
    """A 'what if' weight is scored with the latest stored waist measurement."""
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar(None),                                    # _get_latest_weight
        _row((90.0, datetime(2026, 10, 1, tzinfo=timezone.utc))),  # latest waist
    ]

    with patch(
        "routers.chat.compute_baseline_scores", new=AsyncMock(return_value={})
    ):
        scores = await _build_risk_scores(db, _profile(), "what if i weighed 80 kg")

    line = scores.get("findrisc_hypothetical", "")
    assert line.startswith("Score=")
    db.add.assert_not_called()
