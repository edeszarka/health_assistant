import os
import httpx
import pandas as pd
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Health Dashboard")

# ── Fetch data ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def fetch_summary():
    try:
        with httpx.Client(timeout=10) as c:
            return c.get(f"{BACKEND}/dashboard/summary").json()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=30)
def fetch_bp_readings():
    try:
        with httpx.Client(timeout=10) as c:
            return c.get(f"{BACKEND}/bp/", params={"limit": 30}).json()
    except Exception:
        return []


summary = fetch_summary()
bp_readings = fetch_bp_readings()

if "error" in summary:
    st.error(f"Backend unreachable: {summary['error']}")
    st.stop()

# ── Key metrics ───────────────────────────────────────────────────────────────
bp = summary.get("bp_summary") or {}
flags = summary.get("active_flags", [])
risks = summary.get("risk_scores", [])

col1, col2, col3, col4 = st.columns(4)

with col1:
    cls = bp.get("classification", "No data")
    colour = "🟢" if "Normal" in cls else "🟡" if "Elevated" in cls or "Stage 1" in cls else "🔴"
    st.metric("BP Classification", f"{colour} {cls}")

with col2:
    sys30 = bp.get("avg_systolic_30d")
    dia30 = bp.get("avg_diastolic_30d")
    st.metric(
        "30-day avg BP",
        f"{sys30:.0f}/{dia30:.0f}" if sys30 else "No data",
        delta=bp.get("trend_direction", ""),
    )

with col3:
    st.metric("Active Lab Flags ⚠️", len(flags))

with col4:
    st.metric("BP Readings", bp.get("reading_count", 0))

# ── Flagged labs ──────────────────────────────────────────────────────────────
st.subheader("⚠️ Flagged Lab Values")
if flags:
    for f in flags:
        st.error(f)
else:
    st.success("No flagged lab values.")

# ── Recent risk scores ─────────────────────────────────────────────────────────
st.subheader("🎯 Risk Scores")
if risks:
    df_risk = pd.DataFrame(risks)
    st.dataframe(df_risk, use_container_width=True)
else:
    st.info("No risk scores calculated yet.")

# ── BP trend chart ────────────────────────────────────────────────────────────
st.subheader("📈 Blood Pressure Trend (last 30 readings)")
if bp_readings:
    df = pd.DataFrame(bp_readings)
    df["measured_at"] = pd.to_datetime(df["measured_at"])
    df = df.sort_values("measured_at")
    st.line_chart(
        df.set_index("measured_at")[["systolic", "diastolic", "pulse"]].dropna(axis=1)
    )
else:
    st.info("No BP readings yet. Add some on the Blood Pressure page.")
