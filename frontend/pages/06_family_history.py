import os
import httpx
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Family History", page_icon="🧬", layout="wide")
st.title("🧬 Family Health History")

RELATIONS = [
    "mother",
    "father",
    "maternal_grandmother",
    "maternal_grandfather",
    "paternal_grandmother",
    "paternal_grandfather",
    "sibling",
    "aunt",
    "uncle",
    "child",
    "other",
]

# ── Add entry form ────────────────────────────────────────────────────────────
with st.form("fam_form"):
    st.subheader("Add a condition")
    c1, c2 = st.columns(2)
    with c1:
        relation = st.selectbox("Relative", RELATIONS)
        condition = st.text_input(
            "Medical Condition", placeholder="e.g. Type 2 Diabetes"
        )
    with c2:
        icd10 = st.text_input("ICD-10 Code (optional)", placeholder="e.g. E11")
        age_onset = st.number_input(
            "Age at Onset (optional)", min_value=0, max_value=120, value=0
        )
    notes = st.text_area("Notes (optional)")
    submitted = st.form_submit_button("➕ Add Record")

if submitted and condition:
    payload = {
        "relation": relation,
        "condition": condition,
        "icd10_code": icd10 or None,
        "age_of_onset": int(age_onset) if age_onset > 0 else None,
        "notes": notes or None,
    }
    try:
        resp = httpx.post(f"{BACKEND}/family-history/", json=payload, timeout=30.0)
        resp.raise_for_status()
        st.success("Record added!")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Failed: {e}")

# ── Existing records ──────────────────────────────────────────────────────────
st.subheader("📋 Existing Records")
try:
    entries = httpx.get(f"{BACKEND}/family-history/", timeout=10.0).json()
    if entries:
        for entry in entries:
            with st.expander(
                f"👤 {entry['relation'].replace('_', ' ').title()} — {entry['condition']}"
            ):
                c1, c2 = st.columns([3, 1])
                with c1:
                    if entry.get("icd10_code"):
                        st.write(f"**ICD-10:** {entry['icd10_code']}")
                    if entry.get("age_of_onset"):
                        st.write(f"**Age at onset:** {entry['age_of_onset']}")
                    if entry.get("notes"):
                        st.write(f"**Notes:** {entry['notes']}")
                with c2:
                    if st.button("🗑️ Delete", key=f"del_{entry['id']}"):
                        try:
                            httpx.delete(
                                f"{BACKEND}/family-history/{entry['id']}", timeout=10.0
                            )
                            st.success("Deleted.")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))
    else:
        st.info("No records yet.")
except Exception as e:
    st.error(f"Could not load records: {e}")
