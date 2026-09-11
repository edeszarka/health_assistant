"""Tests for ScreeningService lab-trigger activation."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.screening_service import (
    SCREENING_RULES,
    ScreeningRule,
    ScreeningService,
)


@pytest.fixture
def service() -> ScreeningService:
    return ScreeningService()


async def _recommend(
    service: ScreeningService,
    rules: list[ScreeningRule],
    *,
    age: int = 50,
    sex: str = "male",
    family: list[str] | None = None,
    labs: list[str] | None = None,
) -> list:
    """Run get_recommendations with SCREENING_RULES and MedlinePlus mocked."""
    with patch("services.screening_service.SCREENING_RULES", rules), patch(
        "services.screening_service.medlineplus_service.search_health_topic",
        new=AsyncMock(return_value={"url": None, "summary": ""}),
    ):
        return await service.get_recommendations(
            age=age,
            sex=sex,
            family_history_conditions=family or [],
            flagged_lab_keys=labs or [],
            framingham_score=None,
            findrisc_score=None,
            db=AsyncMock(),
        )


def _names(recs: list) -> list[str]:
    return [r.test_name for r in recs]


@pytest.mark.asyncio
async def test_lab_trigger_fires_when_key_present(service):
    rules = [
        ScreeningRule(
            "Lipid panel",
            20,
            999,
            lab_trigger=["total_cholesterol", "ldl_cholesterol"],
        )
    ]
    recs = await _recommend(service, rules, labs=["ldl_cholesterol"])
    assert _names(recs) == ["Lipid panel"]


@pytest.mark.asyncio
async def test_lab_trigger_absent_when_key_missing(service):
    rules = [ScreeningRule("Lipid panel", 20, 999, lab_trigger=["total_cholesterol"])]
    recs = await _recommend(service, rules, labs=["glucose"])
    assert recs == []


@pytest.mark.asyncio
async def test_lab_trigger_match_is_case_insensitive(service):
    rules = [ScreeningRule("Lipid panel", 20, 999, lab_trigger=["total_cholesterol"])]
    recs = await _recommend(service, rules, labs=["TOTAL_CHOLESTEROL"])
    assert _names(recs) == ["Lipid panel"]


@pytest.mark.asyncio
async def test_rule_without_lab_trigger_behaves_as_before(service):
    rules = [ScreeningRule("Blood pressure screening", 18, 999)]
    recs = await _recommend(service, rules, labs=[])
    assert _names(recs) == ["Blood pressure screening"]


@pytest.mark.asyncio
async def test_family_trigger_only_rule_unchanged(service):
    rules = [
        ScreeningRule(
            "Diabetes screening (HbA1c)", 25, 34, family_trigger=["diabetes"]
        )
    ]
    matched = await _recommend(
        service, rules, age=30, family=["Type 2 diabetes"], labs=[]
    )
    assert _names(matched) == ["Diabetes screening (HbA1c)"]

    unmatched = await _recommend(service, rules, age=30, family=[], labs=[])
    assert unmatched == []


@pytest.mark.asyncio
async def test_family_or_lab_both_activate_rule(service):
    rules = [
        ScreeningRule(
            "Lipid panel",
            20,
            999,
            family_trigger=["cardiovascular disease"],
            lab_trigger=["ldl_cholesterol"],
        )
    ]
    by_family = await _recommend(service, rules, family=["cardiovascular disease"], labs=[])
    by_lab = await _recommend(service, rules, family=[], labs=["ldl_cholesterol"])
    neither = await _recommend(service, rules, family=[], labs=[])

    assert _names(by_family) == ["Lipid panel"]
    assert _names(by_lab) == ["Lipid panel"]
    assert neither == []


@pytest.mark.asyncio
async def test_reason_mentions_triggering_lab(service):
    rules = [ScreeningRule("Lipid panel", 20, 999, lab_trigger=["ldl_cholesterol"])]
    recs = await _recommend(service, rules, labs=["ldl_cholesterol"])
    assert "ldl_cholesterol" in recs[0].reason


@pytest.mark.asyncio
async def test_real_lipid_panel_fires_on_flagged_ldl(service):
    recs = await _recommend(
        service, SCREENING_RULES, age=50, sex="male", family=[], labs=["ldl_cholesterol"]
    )
    assert "Lipid panel" in _names(recs)


@pytest.mark.asyncio
async def test_real_lipid_panel_absent_without_trigger(service):
    recs = await _recommend(
        service, SCREENING_RULES, age=50, sex="male", family=[], labs=[]
    )
    assert "Lipid panel" not in _names(recs)


@pytest.mark.asyncio
async def test_real_diabetes_rule_fires_on_flagged_hba1c(service):
    recs = await _recommend(
        service, SCREENING_RULES, age=30, sex="male", family=[], labs=["hba1c"]
    )
    assert "Diabetes screening (HbA1c)" in _names(recs)
