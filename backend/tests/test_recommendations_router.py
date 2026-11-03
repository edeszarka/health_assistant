"""Tests for the recommendations router: no recommendations without a profile."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers import recommendations


def _fake_db(profile: Optional[Any]) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    result.fetchall.return_value = []
    db = AsyncMock()
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_no_profile_gives_no_recommendations_and_no_lookup():
    """Rules must not run on an invented age, and nothing may go to MedlinePlus."""
    with patch.object(recommendations.screening_service, "get_recommendations", AsyncMock()) as rules, \
         patch.object(recommendations, "compute_baseline_scores", AsyncMock()) as scores:
        result = await recommendations.get_recommendations(db=_fake_db(None))

    assert result == []
    rules.assert_not_called()
    scores.assert_not_called()


@pytest.mark.asyncio
async def test_stored_profile_is_used_for_the_rules():
    profile = SimpleNamespace(age=52, sex="female")
    baseline = {"framingham_risk_percent": None, "findrisc_score": 7}
    with patch.object(recommendations.screening_service, "get_recommendations",
                      AsyncMock(return_value=[])) as rules, \
         patch.object(recommendations, "compute_baseline_scores", AsyncMock(return_value=baseline)):
        await recommendations.get_recommendations(db=_fake_db(profile))

    kwargs = rules.call_args.kwargs
    assert (kwargs["age"], kwargs["sex"], kwargs["findrisc_score"]) == (52, "female", 7)
