"""Deterministic chat reply that lists the stored risk inputs.

Used when the user explicitly asks for a risk calculation: the reply shows
what is stored (value and date), or that nothing is stored, without calling
the LLM, so no value can be invented. The frontend renders the input form
from the same status object.
"""
from __future__ import annotations

from models.api_models import RiskInputsStatus, StoredInput

# Measured inputs, in display order: (status attribute, label key).
_MEASUREMENTS: tuple[str, ...] = (
    "weight_kg", "waist_cm", "systolic_bp", "total_cholesterol", "hdl_cholesterol",
)

_TEXT: dict[str, dict[str, str]] = {
    "Hungarian": {
        "intro": "A kockázatszámításhoz (FINDRISC, Framingham) ezek az adatok vannak tárolva:",
        "profile": "Profil (életkor, nem, magasság, kérdések)",
        "profile_ok": "megvan, életkor: {age} év",
        "weight_kg": "Testsúly",
        "waist_cm": "Derékbőség",
        "systolic_bp": "Szisztolés vérnyomás",
        "total_cholesterol": "Összkoleszterin",
        "hdl_cholesterol": "HDL-koleszterin",
        "bmi (weight and height)": "BMI (testsúly és magasság)",
        "age": "életkor",
        "sex (male/female)": "nem (férfi/nő)",
        "none": "nincs adat",
        "stale": "régi mérés",
        "unconvertible": "az egység nem átváltható, nem használható",
        "findrisc_ready": "FINDRISC: kiszámolható a tárolt adatokból.",
        "findrisc_missing": "FINDRISC: hiányzik: {items}.",
        "framingham_ready": "Framingham: kiszámolható a tárolt adatokból.",
        "framingham_missing": "Framingham: hiányzik: {items}.",
        "framingham_unavailable": "Framingham: nem elérhető ({reason}).",
        "outro": "Az alábbi űrlapon friss adatot vihetsz be, vagy számolhatsz a tárolt értékekkel.",
    },
    "English": {
        "intro": "These inputs are stored for the risk calculation (FINDRISC, Framingham):",
        "profile": "Profile (age, sex, height, questions)",
        "profile_ok": "stored, age: {age} years",
        "weight_kg": "Weight",
        "waist_cm": "Waist circumference",
        "systolic_bp": "Systolic blood pressure",
        "total_cholesterol": "Total cholesterol",
        "hdl_cholesterol": "HDL cholesterol",
        "bmi (weight and height)": "BMI (weight and height)",
        "age": "age",
        "sex (male/female)": "sex (male/female)",
        "none": "no data",
        "stale": "old measurement",
        "unconvertible": "unit cannot be converted, not usable",
        "findrisc_ready": "FINDRISC: can be calculated from the stored data.",
        "findrisc_missing": "FINDRISC: missing {items}.",
        "framingham_ready": "Framingham: can be calculated from the stored data.",
        "framingham_missing": "Framingham: missing {items}.",
        "framingham_unavailable": "Framingham: not available ({reason}).",
        "outro": "Use the form below to enter fresh values, or calculate with the stored ones.",
    },
}


def _value_line(text: dict[str, str], stored: StoredInput) -> str:
    """Describe one stored measurement: value, unit, date and status."""
    if stored.status == "missing" or stored.value is None:
        return text["none"]
    line = f"{stored.value:g} {stored.unit or ''}".strip()
    if stored.recorded_on is not None:
        line += f" ({stored.recorded_on.isoformat()})"
    if stored.status in ("stale", "unconvertible"):
        line += f" — {text[stored.status]}"
    return line


def _names(text: dict[str, str], items: list[str]) -> str:
    """Translate missing-input names for display."""
    return ", ".join(text.get(item, item) for item in items)


def format_risk_inputs(status: RiskInputsStatus, language: str) -> str:
    """Build the chat reply listing the stored risk inputs.

    Args:
        status: The stored inputs and what each score lacks.
        language: ``"Hungarian"`` or ``"English"``; anything else is English.

    Returns:
        A Markdown reply with one line per input and one per score.
    """
    text = _TEXT.get(language, _TEXT["English"])
    profile = (
        text["profile_ok"].format(age=status.age)
        if status.profile is not None else text["none"]
    )
    lines = [text["intro"], "", f"- {text['profile']}: {profile}"]
    for name in _MEASUREMENTS:
        lines.append(f"- {text[name]}: {_value_line(text, getattr(status, name))}")
    lines.append("")
    if status.findrisc_missing:
        lines.append(text["findrisc_missing"].format(items=_names(text, status.findrisc_missing)))
    else:
        lines.append(text["findrisc_ready"])
    if status.framingham_unavailable:
        lines.append(text["framingham_unavailable"].format(reason=status.framingham_unavailable))
    elif status.framingham_missing:
        lines.append(text["framingham_missing"].format(items=_names(text, status.framingham_missing)))
    else:
        lines.append(text["framingham_ready"])
    lines += ["", text["outro"]]
    return "\n".join(lines)
