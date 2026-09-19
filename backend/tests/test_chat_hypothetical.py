"""Tests for unit handling in the hypothetical Framingham fallback."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers.chat import _build_risk_scores


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
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
