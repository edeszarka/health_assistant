"""Explicit lab unit conversion for values consumed by the risk engine.

Hungarian lab reports commonly store lipids and glucose in mmol/L while the
Framingham point tables (Wilson et al. 1998) expect mg/dL. This module makes
that conversion explicit; it never guesses a unit.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Molar-mass conversion factors: mg/dL = mmol/L * factor.
# Each factor is the compound's molar mass in g/mol divided by 10, because
# 1 mmol/L * (g/mol) / 10 = mg/dL.
#   total/HDL/LDL cholesterol: cholesterol MW 386.65 g/mol → 38.67
#   triglycerides: triolein MW 885.4 g/mol → 88.57
#   glucose: glucose MW 180.16 g/mol → 18.016
# Reference: SI-to-conventional unit conversion tables, NEJM / AMA Manual.
MOLAR_MASS_FACTORS: dict[str, float] = {
    "total_cholesterol": 38.67,
    "hdl_cholesterol": 38.67,
    "ldl_cholesterol": 38.67,
    "triglycerides": 88.57,
    "glucose": 18.016,
}


class LabUnitConverter:
    """Converts known lab units to the mg/dL convention used by risk scores."""

    _MG_DL_UNITS: frozenset[str] = frozenset({"mg/dl"})
    _MMOL_L_UNITS: frozenset[str] = frozenset({"mmol/l"})

    def to_mg_dl(self, test_name: str, value: float, unit: str | None) -> float | None:
        """Convert a lab value to mg/dL when the unit is recognised.

        Args:
            test_name: Normalised lab key (e.g. ``total_cholesterol``).
            value: The numeric result as stored in the lab report.
            unit: The raw unit string from the report, or ``None``.

        Returns:
            The value in mg/dL, or ``None`` when the unit is missing,
            unrecognised, already non-convertible, or the test name has no
            known conversion factor. A warning is logged in every ``None`` case.
        """
        normalized_unit = (unit or "").strip().lower()

        if normalized_unit in self._MG_DL_UNITS:
            return float(value)

        if normalized_unit in self._MMOL_L_UNITS:
            factor = MOLAR_MASS_FACTORS.get(test_name)
            if factor is None:
                logger.warning(
                    "No mmol/L→mg/dL conversion factor for test '%s'; skipping.",
                    test_name,
                )
                return None
            return float(value) * factor

        logger.warning(
            "Unrecognised or missing unit '%s' for test '%s'; refusing to guess.",
            unit,
            test_name,
        )
        return None


lab_unit_converter = LabUnitConverter()
