import os
import httpx
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Recommendations", page_icon="📋", layout="wide")
st.title("📋 Preventive Screening Recommendations")
st.caption("Personalised based on your age, sex, family history, and risk scores.")

URGENCY_CONFIG = {
    "urgent": ("🔴 Urgent", "red"),
    "soon": ("🟠 Soon", "orange"),
    "routine": ("🟢 Routine", "green"),
}

try:
    recs = httpx.get(f"{BACKEND}/recommendations/", timeout=1200.0).json()
except Exception as e:
    st.error(f"Could not load recommendations: {e}")
    st.stop()

if not recs:
    st.info("No recommendations at this time. Add your profile data to get started.")
    st.stop()

# Group by urgency
groups: dict[str, list] = {"urgent": [], "soon": [], "routine": []}
for r in recs:
    groups.setdefault(r.get("urgency", "routine"), []).append(r)

for urgency, label_cfg in URGENCY_CONFIG.items():
    label, colour = label_cfg
    items = groups.get(urgency, [])
    if not items:
        continue
    st.subheader(label)
    for rec in items:
        with st.container():
            col1, col2 = st.columns([5, 1])
            with col1:
                st.checkbox(
                    f"**{rec['test_name']}**",
                    key=f"rec_{rec['test_name']}_{urgency}",
                )
                st.write(f"📝 {rec.get('reason', '')}")
                st.write(f"👨‍⚕️ Specialist: **{rec.get('specialist', 'GP')}**")
                summary = rec.get("medlineplus_summary", "")
                if summary:
                    st.caption(
                        f"ℹ️ {summary[:300]}…" if len(summary) > 300 else f"ℹ️ {summary}"
                    )
            with col2:
                url = rec.get("medlineplus_url")
                if url:
                    st.link_button("MedlinePlus 🔗", url)
            st.divider()
