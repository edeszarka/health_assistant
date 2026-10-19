"""In-chat risk input form: show stored values, save fresh ones, calculate.

Rendered by the chat page when the backend answers a risk request with a
``data_request``. Saving goes to ``PUT /risk/inputs`` (and ``POST /bp/`` for a
new blood pressure reading); the calculation to ``POST /risk/calculate``,
which also persists the scores.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

import httpx
import streamlit as st

TIMEOUT_S = 60.0
FAMILY_OPTIONS = ("none", "second_degree", "first_degree")
UNITS = ("mmol/L", "mg/dL")

TEXT: dict[str, dict[str, str]] = {
    "Hungarian": {
        "title": "Kockázatszámítás adatai",
        "profile": "Profil",
        "birth_year": "Születési év", "birth_month": "Születési hónap",
        "sex": "Biológiai nem (a számításhoz)", "male": "férfi", "female": "nő",
        "height_cm": "Magasság (cm)",
        "smoking": "Dohányzom",
        "bp_medication_ever": "Szedtem valaha rendszeresen vérnyomáscsökkentőt",
        "bp_medication_current": "Jelenleg szedek vérnyomáscsökkentőt",
        "high_glucose_history": "Mértek már nálam magas vércukrot",
        "diabetes_diagnosed": "Diagnosztizált cukorbetegségem van",
        "vegetables_daily": "Naponta eszem zöldséget vagy gyümölcsöt",
        "physically_active": "Naponta legalább 30 percet mozgok",
        "family_diabetes": "Cukorbeteg rokon",
        "none": "nincs", "second_degree": "nagyszülő, nagynéni, nagybácsi, unokatestvér",
        "first_degree": "szülő, testvér, gyermek",
        "measurements": "Friss mérések (üresen hagyva a tárolt érték marad)",
        "weight_kg": "Testsúly (kg)", "waist_cm": "Derékbőség (cm)",
        "systolic": "Szisztolés vérnyomás", "diastolic": "Diasztolés vérnyomás",
        "total_cholesterol": "Összkoleszterin", "hdl_cholesterol": "HDL-koleszterin",
        "unit": "Egység", "lab_date": "Laborvizsgálat dátuma",
        "stored": "Tárolt", "no_data": "nincs adat",
        "use_stored": "Számolj a tárolt adatokkal", "save": "Mentés és számolás",
        "required": "Add meg a születési évet, hónapot, a nemet és a magasságot.",
        "bp_pair": "A vérnyomáshoz a szisztolés és a diasztolés érték is kell.",
        "saved_scores": "Az eredményt elmentettem.",
        "findrisc": "FINDRISC (2-es típusú cukorbetegség, 10 év): {score} pont – {category}",
        "framingham": "Framingham (szív- és érrendszeri, 10 év): {pct:g}% – {category}",
        "not_calculated": "{name}: nem számolható – hiányzik: {items}",
        "unavailable": "{name}: nem elérhető ({reason})",
        "error": "Hiba",
    },
    "English": {
        "title": "Risk calculation inputs",
        "profile": "Profile",
        "birth_year": "Birth year", "birth_month": "Birth month",
        "sex": "Biological sex (for the scores)", "male": "male", "female": "female",
        "height_cm": "Height (cm)",
        "smoking": "I smoke",
        "bp_medication_ever": "I have ever taken BP medication regularly",
        "bp_medication_current": "I currently take BP medication",
        "high_glucose_history": "High blood glucose has been found before",
        "diabetes_diagnosed": "I have diagnosed diabetes",
        "vegetables_daily": "I eat vegetables or fruit every day",
        "physically_active": "I am physically active at least 30 minutes daily",
        "family_diabetes": "Relative with diabetes",
        "none": "none", "second_degree": "grandparent, aunt, uncle, cousin",
        "first_degree": "parent, sibling, child",
        "measurements": "Fresh measurements (leave empty to keep the stored value)",
        "weight_kg": "Weight (kg)", "waist_cm": "Waist circumference (cm)",
        "systolic": "Systolic BP", "diastolic": "Diastolic BP",
        "total_cholesterol": "Total cholesterol", "hdl_cholesterol": "HDL cholesterol",
        "unit": "Unit", "lab_date": "Lab test date",
        "stored": "Stored", "no_data": "no data",
        "use_stored": "Calculate with stored data", "save": "Save and calculate",
        "required": "Enter birth year, birth month, sex and height.",
        "bp_pair": "A blood pressure reading needs both systolic and diastolic.",
        "saved_scores": "The result has been saved.",
        "findrisc": "FINDRISC (type 2 diabetes, 10 years): {score} points – {category}",
        "framingham": "Framingham (cardiovascular, 10 years): {pct:g}% – {category}",
        "not_calculated": "{name}: not calculated – missing {items}",
        "unavailable": "{name}: not available ({reason})",
        "error": "Error",
    },
}

PROFILE_FLAGS = (
    "smoking", "bp_medication_ever", "bp_medication_current",
    "high_glucose_history", "diabetes_diagnosed", "vegetables_daily",
    "physically_active",
)


# ── Backend calls ────────────────────────────────────────────────────────────

def _call(backend: str, method: str, path: str, payload: Optional[dict] = None) -> dict:
    """Call the backend and return the JSON body; raise RuntimeError with the detail."""
    try:
        resp = httpx.request(method, f"{backend}{path}", json=payload, timeout=TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(_detail(exc.response)) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(str(exc)) from exc


def _detail(response: httpx.Response) -> str:
    """Extract a readable error from a FastAPI error response."""
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        return response.text
    if isinstance(detail, list):  # 422 validation errors
        return "; ".join(str(item.get("msg", item)) for item in detail)
    return str(detail)


# ── Rendering helpers ────────────────────────────────────────────────────────

def _stored_caption(t: dict[str, str], stored: dict[str, Any]) -> str:
    """One-line description of a stored measurement."""
    if stored.get("value") is None:
        return f"{t['stored']}: {t['no_data']}"
    when = f" ({stored['recorded_on']})" if stored.get("recorded_on") else ""
    return f"{t['stored']}: {stored['value']:g} {stored.get('unit') or ''}{when}"


def can_use_stored(status: dict[str, Any]) -> bool:
    """Whether at least one score can be calculated from the stored inputs."""
    findrisc_ready = not status["findrisc_missing"]
    framingham_ready = not status["framingham_missing"] and not status.get(
        "framingham_unavailable"
    )
    return findrisc_ready or framingham_ready


def format_result(result: dict[str, Any], t: dict[str, str]) -> str:
    """Build the chat message for a calculation result."""
    inputs = result["inputs"]
    lines = []
    if result.get("findrisc_score") is not None:
        lines.append(t["findrisc"].format(
            score=result["findrisc_score"], category=result["findrisc_category"]))
    else:
        lines.append(t["not_calculated"].format(
            name="FINDRISC", items=", ".join(inputs["findrisc_missing"])))
    if result.get("framingham_risk_percent") is not None:
        lines.append(t["framingham"].format(
            pct=result["framingham_risk_percent"], category=result["framingham_category"]))
    elif inputs.get("framingham_unavailable"):
        lines.append(t["unavailable"].format(
            name="Framingham", reason=inputs["framingham_unavailable"]))
    else:
        lines.append(t["not_calculated"].format(
            name="Framingham", items=", ".join(inputs["framingham_missing"])))
    if any(result.get(k) is not None for k in ("findrisc_score", "framingham_risk_percent")):
        lines.append(t["saved_scores"])
    return "\n\n".join(lines)


def _profile_inputs(t: dict[str, str], profile: dict[str, Any]) -> dict[str, Any]:
    """Render the profile fields; returns the entered values."""
    st.markdown(f"**{t['profile']}**")
    c1, c2, c3, c4 = st.columns(4)
    values: dict[str, Any] = {
        "birth_year": c1.number_input(
            t["birth_year"], min_value=1900, max_value=date.today().year,
            value=profile.get("birth_year"), step=1),
        "birth_month": c2.selectbox(
            t["birth_month"], list(range(1, 13)),
            index=profile["birth_month"] - 1 if profile.get("birth_month") else None),
        "sex": c3.selectbox(
            t["sex"], ["male", "female"], format_func=lambda s: t[s],
            index=["male", "female"].index(profile["sex"]) if profile.get("sex") else None),
        "height_cm": c4.number_input(
            t["height_cm"], min_value=100, max_value=250,
            value=profile.get("height_cm"), step=1),
    }
    for flag in PROFILE_FLAGS:
        values[flag] = st.checkbox(t[flag], value=bool(profile.get(flag, False)))
    current = profile.get("family_diabetes", "none")
    values["family_diabetes"] = st.radio(
        t["family_diabetes"], FAMILY_OPTIONS, format_func=lambda o: t[o],
        index=FAMILY_OPTIONS.index(current), horizontal=True)
    return values


def _measurement_inputs(t: dict[str, str], status: dict[str, Any]) -> dict[str, Any]:
    """Render the optional fresh measurements; returns the entered values."""
    st.markdown(f"**{t['measurements']}**")
    c1, c2, c3, c4 = st.columns(4)
    values: dict[str, Any] = {
        "weight_kg": c1.number_input(t["weight_kg"], min_value=25.0, max_value=350.0,
                                     value=None, step=0.1),
        "waist_cm": c2.number_input(t["waist_cm"], min_value=40.0, max_value=200.0,
                                    value=None, step=0.5),
        "systolic": c3.number_input(t["systolic"], min_value=60, max_value=260,
                                    value=None, step=1),
        "diastolic": c4.number_input(t["diastolic"], min_value=30, max_value=160,
                                     value=None, step=1),
    }
    c1.caption(_stored_caption(t, status["weight_kg"]))
    c2.caption(_stored_caption(t, status["waist_cm"]))
    c3.caption(_stored_caption(t, status["systolic_bp"]))
    c1, c2, c3, c4, c5 = st.columns(5)
    values["total_cholesterol"] = c1.number_input(
        t["total_cholesterol"], min_value=0.0, value=None, step=0.1)
    values["tc_unit"] = c2.selectbox(t["unit"], UNITS, key="tc_unit")
    values["hdl_cholesterol"] = c3.number_input(
        t["hdl_cholesterol"], min_value=0.0, value=None, step=0.1)
    values["hdl_unit"] = c4.selectbox(t["unit"], UNITS, key="hdl_unit")
    values["lab_date"] = c5.date_input(t["lab_date"], value=date.today(),
                                       max_value=date.today())
    c1.caption(_stored_caption(t, status["total_cholesterol"]))
    c3.caption(_stored_caption(t, status["hdl_cholesterol"]))
    return values


# ── Actions ──────────────────────────────────────────────────────────────────

def build_payload(profile: dict[str, Any], m: dict[str, Any]) -> dict[str, Any]:
    """Build the PUT /risk/inputs body from the entered values."""
    payload: dict[str, Any] = {
        "profile": {**profile, "birth_year": int(profile["birth_year"]),
                    "height_cm": int(profile["height_cm"])},
        "weight_kg": m["weight_kg"],
        "waist_cm": m["waist_cm"],
    }
    for name, unit_key in (("total_cholesterol", "tc_unit"), ("hdl_cholesterol", "hdl_unit")):
        if m[name] is not None:
            payload[name] = {"value": m[name], "unit": m[unit_key],
                             "test_date": m["lab_date"].isoformat()}
    return payload


def _save(backend: str, t: dict[str, str], profile: dict, m: dict) -> None:
    """Validate locally, then save the BP reading and the risk inputs."""
    if any(profile[k] is None for k in ("birth_year", "birth_month", "sex", "height_cm")):
        raise RuntimeError(t["required"])
    if (m["systolic"] is None) != (m["diastolic"] is None):
        raise RuntimeError(t["bp_pair"])
    _call(backend, "PUT", "/risk/inputs", build_payload(profile, m))
    if m["systolic"] is not None:
        _call(backend, "POST", "/bp/", {"systolic": int(m["systolic"]),
                                        "diastolic": int(m["diastolic"])})


def render_risk_form(backend: str, request: dict[str, Any]) -> Optional[str]:
    """Render the form; return the result message once a calculation ran.

    Args:
        backend: Backend base URL.
        request: ``{"status": RiskInputsStatus dict, "language": str}``.

    Returns:
        The chat message describing the result, or ``None`` while the form
        is still open (nothing submitted, or an error was shown).
    """
    status = request["status"]
    t = TEXT.get(request.get("language", "English"), TEXT["English"])
    with st.form("risk_form"):
        st.subheader(t["title"])
        profile = _profile_inputs(t, status.get("profile") or {})
        measurements = _measurement_inputs(t, status)
        c1, c2 = st.columns(2)
        use_stored = c1.form_submit_button(t["use_stored"], disabled=not can_use_stored(status))
        save = c2.form_submit_button(t["save"], type="primary")
    if not (use_stored or save):
        return None
    try:
        if save:
            _save(backend, t, profile, measurements)
        result = _call(backend, "POST", "/risk/calculate")
    except RuntimeError as exc:
        st.error(f"{t['error']}: {exc}")
        return None
    return format_result(result, t)
