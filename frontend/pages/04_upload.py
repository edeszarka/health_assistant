import os
import httpx
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Upload", page_icon="📂", layout="wide")
st.title("📂 Upload Medical Data")

tab_pdf, tab_samsung, tab_zepp = st.tabs(
    ["🗒️ Lab PDF", "📱 Samsung Health", "⌚ Zepp Life"]
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
    samsung_files = st.file_uploader(
        "Choose the Samsung Health ZIP file",
        type=["zip", "csv"],
        accept_multiple_files=True,
        key="samsung_upload",
    )
    if samsung_files and st.button("Process Samsung Data", key="process_samsung"):
        with st.spinner("Parsing Samsung Health data…"):
            try:
                # Use _mime() to ensure consistent MIME type — f.type is unreliable for ZIPs
                httpx_files = [
                    ("files", (f.name, f.getvalue(), _mime(f.name)))
                    for f in samsung_files
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

# ── Zepp Life tab ─────────────────────────────────────────────────────────────
with tab_zepp:
    st.subheader("Upload Zepp Life Export")
    st.info(
        "Export from Zepp Life app → Profile → Privacy and Account → "
        "Download Personal Data. The export ZIP is password protected — "
        "the password is shown in the confirmation email from Zepp."
    )
    zepp_files = st.file_uploader(
        "Choose the Zepp Life ZIP file",
        type=["zip", "csv"],
        accept_multiple_files=True,
        key="zepp_upload",
    )
    zepp_password = st.text_input(
        "ZIP Password (from Zepp confirmation email)",
        value="",
        type="password",
        placeholder="Enter the password from your Zepp export email",
    )

    if zepp_files and st.button("Process Zepp Data", key="process_zepp"):
        if not zepp_password:
            st.warning(
                "⚠️ No password entered. If the ZIP is password-protected the upload will fail."
            )

        with st.spinner("Parsing Zepp Life data…"):
            try:
                httpx_files = [
                    ("files", (f.name, f.getvalue(), _mime(f.name))) for f in zepp_files
                ]
                data = {}
                if zepp_password:
                    data["password"] = zepp_password

                resp = httpx.post(
                    f"{BACKEND}/upload/zepp",
                    files=httpx_files,
                    data=data,
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
