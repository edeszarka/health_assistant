import os
from datetime import datetime, timezone
import httpx
import pandas as pd
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Blood Pressure", page_icon="💉", layout="wide")
st.title("💉 Blood Pressure Tracker")

CLASSIFICATION_COLOURS = {
    "Normal": "🟢",
    "Elevated": "🟡",
    "Stage 1 Hypertension": "🟠",
    "Stage 2 Hypertension": "🔴",
    "Hypertensive Crisis": "🚨",
}

# ── Entry form ────────────────────────────────────────────────────────────────
with st.form("bp_form"):
    st.subheader("New Reading")
    c1, c2, c3 = st.columns(3)
    with c1:
        systolic = st.number_input(
            "Systolic (mmHg)", min_value=50, max_value=300, value=120
        )
    with c2:
        diastolic = st.number_input(
            "Diastolic (mmHg)", min_value=30, max_value=200, value=80
        )
    with c3:
        pulse = st.number_input("Pulse (bpm)", min_value=30, max_value=250, value=72)
    context = st.selectbox(
        "Context", ["", "morning", "evening", "after_exercise", "stressed"]
    )
    measured_at = st.date_input("Date", value=datetime.now().date())
    submitted = st.form_submit_button("💾 Save Reading")

if submitted:
    payload = {
        "systolic": int(systolic),
        "diastolic": int(diastolic),
        "pulse": int(pulse),
        "context": context or None,
        "measured_at": datetime.combine(measured_at, datetime.min.time()).isoformat(),
    }
    try:
        resp = httpx.post(f"{BACKEND}/bp/", json=payload, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        cls = data.get("classification", "")
        icon = CLASSIFICATION_COLOURS.get(cls, "")
        st.success(f"Saved! Classification: {icon} **{cls}**")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Failed to save: {e}")

# ── Summary strip ─────────────────────────────────────────────────────────────
try:
    summary = httpx.get(f"{BACKEND}/bp/summary", timeout=10.0).json()
    s1, s2, s3 = st.columns(3)
    with s1:
        cls = summary.get("classification", "No data")
        icon = CLASSIFICATION_COLOURS.get(cls, "")
        st.metric("Classification", f"{icon} {cls}")
    with s2:
        s7 = summary.get("avg_systolic_7d")
        d7 = summary.get("avg_diastolic_7d")
        st.metric("7-day avg", f"{s7:.0f}/{d7:.0f}" if s7 else "—")
    with s3:
        trend = summary.get("trend_direction", "stable")
        icons = {"improving": "📉", "stable": "➡️", "worsening": "📈"}
        st.metric("Trend", f"{icons.get(trend, '')} {trend}")
except Exception:
    pass

# ── Chart ─────────────────────────────────────────────────────────────────────
st.subheader("📈 Last 30 Readings")
try:
    readings = httpx.get(f"{BACKEND}/bp/", params={"limit": 30}, timeout=10.0).json()
    if readings:
        df = pd.DataFrame(readings)
        df["measured_at"] = pd.to_datetime(df["measured_at"])
        df = df.sort_values("measured_at")
        st.line_chart(
            df.set_index("measured_at")[["systolic", "diastolic", "pulse"]].dropna(
                axis=1
            )
        )
    else:
        st.info("No readings yet.")
except Exception as e:
    st.warning(f"Could not load chart: {e}")
