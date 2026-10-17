import os
import httpx
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Upload", page_icon="📂", layout="wide")
st.title("📂 Upload Medical Data")

tab_pdf, tab_samsung = st.tabs(
    ["🗒️ Lab PDF", "📱 Samsung Health"]
)


def _mime(filename: str) -> str:
    """Return a consistent MIME type based on file extension."""
    ext = filename.lower().rsplit(".", 1)[-1]
    return {
        "pdf": "application/pdf",
        "zip": "application/octet-stream",
        "csv": "text/csv",
    }.get(ext, "application/octet-stream")


# ── Lab PDF tab ───────────────────────────────────────────────────────────────
with tab_pdf:
    st.subheader("Upload a Lab Result PDF")
    st.info(
        "The AI will extract lab values automatically. "
        "Supports Hungarian, Latin, and English medical terminology."
    )
    pdf_file = st.file_uploader("Choose a PDF file", type=["pdf"], key="pdf_upload")
    if pdf_file and st.button("Process PDF", key="process_pdf"):
        with st.spinner("Extracting lab values via AI (this may take up to 60s)…"):
            try:
                resp = httpx.post(
                    f"{BACKEND}/upload/pdf",
                    files={
                        "file": (pdf_file.name, pdf_file.getvalue(), "application/pdf")
                    },
                    timeout=1200.0,
                )
                resp.raise_for_status()
                result = resp.json()
                st.success(
                    f"✅ Processed **{result.get('filename')}**: "
                    f"extracted {result.get('extracted', 0)}, "
                    f"stored {result.get('stored', 0)} results."
                )
                for warning in result.get("warnings") or []:
                    st.warning(warning)
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", e.response.text)
                except Exception:
                    detail = e.response.text
                st.error(f"Upload failed: {detail}")
            except Exception as e:
                st.error(f"Upload failed: {e}")

# ── Samsung Health tab ────────────────────────────────────────────────────────
with tab_samsung:
    st.subheader("Upload Samsung Health Export")
    st.info(
        "Export from Samsung Health app → Profile → Settings → Download personal data. "
        "Upload the resulting ZIP file. Supports steps, distance, calories, weight."
    )
    samsung_file = st.file_uploader(
        "Choose the Samsung Health ZIP file",
        type=["zip"],
        key="samsung_upload",
    )
    if samsung_file and st.button("Process Samsung Data", key="process_samsung"):
        with st.spinner("Parsing Samsung Health data…"):
            try:
                # Use _mime() to ensure consistent MIME type — f.type is unreliable for ZIPs
                httpx_files = [
                    (
                        "files",
                        (samsung_file.name, samsung_file.getvalue(), _mime(samsung_file.name)),
                    )
                ]
                resp = httpx.post(
                    f"{BACKEND}/upload/samsung",
                    files=httpx_files,
                    timeout=1200.0,
                )
                resp.raise_for_status()
                result = resp.json()
                st.success(
                    f"✅ Processed **{result.get('filename')}**: "
                    f"{result.get('metrics_extracted', 0)} days extracted, "
                    f"{result.get('stored', 0)} metrics stored."
                )
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json().get("detail", e.response.text)
                except Exception:
                    detail = e.response.text
                st.error(f"Upload failed: {detail}")
            except Exception as e:
                st.error(f"Upload failed: {e}")
