"""Tests for the /risk endpoints and the user_profile migration decision."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from database.connection import get_db
from main import app
from models.api_models import RiskInputsStatus, StoredInput
from routers import risk
from scripts.migrate_user_profile import decide


def _status() -> RiskInputsStatus:
    return RiskInputsStatus(
        weight_kg=StoredInput(), waist_cm=StoredInput(), systolic_bp=StoredInput(),
        total_cholesterol=StoredInput(), hdl_cholesterol=StoredInput(),
        findrisc_missing=["profile"], framingham_missing=["profile"],
    )


@pytest.fixture
def fake_db():
    db = AsyncMock()

    async def override():
        yield db

    app.dependency_overrides[get_db] = override
    yield db
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_calculate_computes_with_stored_profile_and_returns_inputs(client, fake_db):
    profile = SimpleNamespace(sex="male")
    scores = {
        "findrisc_score": 7, "findrisc_category": "Slightly elevated",
        "framingham_risk_percent": None, "framingham_category": None,
    }
    with patch.object(risk, "load_profile", AsyncMock(return_value=profile)), \
         patch.object(risk, "compute_baseline_scores", AsyncMock(return_value=scores)) as compute, \
         patch.object(risk, "collect_inputs", AsyncMock(return_value=_status())):
        resp = await client.post("/risk/calculate")

    assert resp.status_code == 200
    compute.assert_awaited_once_with(fake_db, profile)
    body = resp.json()
    assert body["findrisc_score"] == 7
    assert body["inputs"]["findrisc_missing"] == ["profile"]


@pytest.mark.asyncio
async def test_put_inputs_rejects_invalid_profile_without_saving(client, fake_db):
    with patch.object(risk, "save_inputs", AsyncMock()) as save:
        resp = await client.put("/risk/inputs", json={"profile": {"sex": "male"}})

    assert resp.status_code == 422
    save.assert_not_called()


@pytest.mark.asyncio
async def test_get_inputs_returns_status(client, fake_db):
    with patch.object(risk, "collect_inputs", AsyncMock(return_value=_status())):
        resp = await client.get("/risk/inputs")

    assert resp.status_code == 200
    assert resp.json()["weight_kg"]["status"] == "missing"


def test_migration_refuses_outdated_table_with_rows():
    assert decide({"id", "age", "sex"}, row_count=1) == "refuse"


def test_migration_recreates_outdated_empty_table():
    assert decide({"id", "age", "sex"}, row_count=0) == "recreate"


def test_migration_leaves_current_table_alone():
    assert decide({"id", "birth_year", "sex"}, row_count=3) == "up_to_date"


def test_migration_creates_missing_table():
    assert decide(None, row_count=0) == "create"
