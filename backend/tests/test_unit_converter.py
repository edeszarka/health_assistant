"""Tests for LabUnitConverter — explicit mmol/L to mg/dL handling."""
from __future__ import annotations

import pytest

from ingestion.unit_converter import MOLAR_MASS_FACTORS, LabUnitConverter


@pytest.fixture
def converter() -> LabUnitConverter:
    return LabUnitConverter()


@pytest.mark.parametrize(
    "test_name,value",
    [
        ("total_cholesterol", 5.2),
        ("hdl_cholesterol", 1.3),
        ("ldl_cholesterol", 3.1),
        ("triglycerides", 1.7),
        ("glucose", 5.5),
    ],
)
def test_mmol_l_converts_to_mg_dl(converter, test_name, value):
    """Each supported test name is multiplied by its documented factor."""
    result = converter.to_mg_dl(test_name, value, "mmol/L")
    assert result == pytest.approx(value * MOLAR_MASS_FACTORS[test_name])


@pytest.mark.parametrize("unit", ["mg/dL", "mg/dl"])
def test_mg_dl_passthrough_both_casing(converter, unit):
    """Already-converted mg/dL values are returned unchanged."""
    assert converter.to_mg_dl("total_cholesterol", 200.0, unit) == 200.0


def test_mg_dl_passthrough_is_not_double_converted(converter):
    """A second conversion request on an mg/dL value must not multiply it again."""
    first = converter.to_mg_dl("total_cholesterol", 200.0, "mg/dL")
    assert first == 200.0
    assert converter.to_mg_dl("total_cholesterol", first, "mg/dL") == 200.0


def test_missing_unit_returns_none(converter):
    """A None unit is never assumed; conversion is refused."""
    assert converter.to_mg_dl("total_cholesterol", 5.2, None) is None


def test_empty_unit_returns_none(converter):
    """An empty unit string is treated like a missing unit."""
    assert converter.to_mg_dl("total_cholesterol", 5.2, "") is None


def test_unknown_unit_returns_none(converter):
    """An unrecognised unit string is refused instead of guessed."""
    assert converter.to_mg_dl("total_cholesterol", 5.2, "g/L") is None


def test_unknown_test_name_returns_none(converter):
    """A test name without a known factor cannot be converted."""
    assert converter.to_mg_dl("creatinine", 5.2, "mmol/L") is None
