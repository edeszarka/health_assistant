import streamlit as st

st.set_page_config(
    page_title="Health Assistant",
    page_icon="🏥",
    layout="wide",
)

st.title("🏥 Personal Health Assistant")
st.caption("AI-powered health insights from your lab results and wearable data.")
st.warning(
    "⚠️ This tool is for informational purposes only. "
    "Always consult a licensed physician before making any medical decisions."
)

st.markdown(
    """
Use the sidebar to navigate between sections:

| Page | Description |
|------|-------------|
| 📊 Dashboard | Overview of your health data |
| 💬 Chat | Ask your AI health assistant |
| 📂 Upload | Import lab PDFs or Samsung Health data |
| 💉 Blood Pressure | Track BP readings over time |
| 🧬 Family History | Record hereditary conditions |
| 📋 Recommendations | Personalised screening checklist |
"""
)
