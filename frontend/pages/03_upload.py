import os
import httpx
import pandas as pd
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Upload", page_icon="📂", layout="wide")
st.title("📂 Upload Medical Data")

tab_pdf, tab_samsung = st.tabs(["🗒️ Lab PDF", "📱 Samsung Health"])

# ── Lab PDF tab ───────────────────────────────────────────────────────────────
with tab_pdf:
    st.subheader("Upload a Lab Result PDF")
    st.info(
        "The AI will extract lab values automatically. "
        "Supports Hungarian, Latin, and English medical terminology."
    )
    pdf_file = st.file_uploader("Choose a PDF file", type="pdf", key="pdf_upload")
    if pdf_file and st.button("Process PDF", key="process_pdf"):
        with st.spinner("Extracting lab values via AI (this may take up to 60s)…"):
            try:
                resp = httpx.post(
                    f"{BACKEND}/upload/pdf",
                    files={"file": (pdf_file.name, pdf_file.getvalue(), "application/pdf")},
                    timeout=120.0,
                )
                resp.raise_for_status()
                result = resp.json()
                st.success(
                    f"✅ Processed **{result.get('filename')}**: "
                    f"extracted {result.get('extracted', 0)}, "
                    f"stored {result.get('stored', 0)} results."
                )
            except Exception as e:
                st.error(f"Upload failed: {e}")

# ── Samsung Health tab ────────────────────────────────────────────────────────
with tab_samsung:
    st.subheader("Upload Samsung Health Export (.zip)")
    st.info(
        "Export your data from the Samsung Health app (Settings → Export). "
        "Supports steps, sleep, heart rate, and body composition."
    )
    zip_file = st.file_uploader("Choose a ZIP file", type="zip", key="zip_upload")
    if zip_file and st.button("Process ZIP", key="process_zip"):
        with st.spinner("Parsing Samsung Health data…"):
            try:
                resp = httpx.post(
                    f"{BACKEND}/upload/samsung",
                    files={"file": (zip_file.name, zip_file.getvalue(), "application/zip")},
                    timeout=60.0,
                )
                resp.raise_for_status()
                result = resp.json()
                st.success(
                    f"✅ Processed **{result.get('filename')}**: "
                    f"{result.get('metrics_extracted', 0)} metrics extracted, "
                    f"{result.get('stored', 0)} stored."
                )
            except Exception as e:
                st.error(f"Upload failed: {e}")
