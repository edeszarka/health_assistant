"""LOINC codes for the normalised lab keys, used for MedlinePlus Connect.

Each code was checked on 2026-10-19 against the LOINC code system with the
HL7 FHIR terminology server (``tx.fhir.org/r4/CodeSystem/$lookup``); the
LOINC long common name is given next to it. A lab key without a code here
simply gets no MedlinePlus reference. The list is fixed and independent of
the user's results, so prefetching it reveals nothing about the user.
"""
from __future__ import annotations

LAB_LOINC: dict[str, str] = {
    # Blood count
    "wbc": "6690-2",              # Leukocytes [#/volume] in Blood by Automated count
    "rbc": "789-8",               # Erythrocytes [#/volume] in Blood by Automated count
    "hemoglobin": "718-7",        # Hemoglobin [Mass/volume] in Blood
    "hematocrit": "4544-3",       # Hematocrit [Volume Fraction] of Blood by Automated count
    "platelets": "777-3",         # Platelets [#/volume] in Blood by Automated count
    "mcv": "787-2",               # MCV [Entitic mean volume] in Red Blood Cells
    "mch": "785-6",               # MCH [Entitic mass] by Automated count
    "mchc": "786-4",              # MCHC [Entitic Mass/volume] in Red Blood Cells
    "mpv": "32623-1",             # Platelet [Entitic mean volume] in Blood
    "esr": "4537-7",              # Erythrocyte [Sedimentation Rate] by Westergren method
    "lymphocytes_pct": "736-9",   # Lymphocytes/Leukocytes in Blood
    "monocytes_pct": "5905-5",    # Monocytes/Leukocytes in Blood
    "neutrophils_pct": "770-8",   # Neutrophils/Leukocytes in Blood
    "eosinophils_pct": "713-8",   # Eosinophils/Leukocytes in Blood
    "basophils_pct": "706-2",     # Basophils/Leukocytes in Blood
    "lymphocytes_abs": "731-0",   # Lymphocytes [#/volume] in Blood
    "monocytes_abs": "742-7",     # Monocytes [#/volume] in Blood
    "neutrophils_abs": "751-8",   # Neutrophils [#/volume] in Blood
    "eosinophils_abs": "711-2",   # Eosinophils [#/volume] in Blood
    "basophils_abs": "704-7",     # Basophils [#/volume] in Blood
    # Metabolic / kidney
    "glucose": "2345-7",          # Glucose [Mass/volume] in Serum or Plasma
    "hba1c": "4548-4",            # Hemoglobin A1c/Hemoglobin.total in Blood
    "bun": "3094-0",              # Urea nitrogen [Mass/volume] in Serum or Plasma
    "creatinine": "2160-0",       # Creatinine [Mass/volume] in Serum or Plasma
    "uric_acid": "3084-1",        # Urate [Mass/volume] in Serum or Plasma
    "egfr": "33914-3",            # Glomerular filtration rate ... (MDRD)/1.73 sq M
    # Electrolytes
    "sodium": "2951-2",           # Sodium [Moles/volume] in Serum or Plasma
    "potassium": "2823-3",        # Potassium [Moles/volume] in Serum or Plasma
    "calcium": "17861-6",         # Calcium [Mass/volume] in Serum or Plasma
    "magnesium": "19123-9",       # Magnesium [Mass/volume] in Serum or Plasma
    "chloride": "2075-0",         # Chloride [Moles/volume] in Serum or Plasma
    # Liver
    "ast": "1920-8",              # Aspartate aminotransferase in Serum or Plasma
    "alt": "1742-6",              # Alanine aminotransferase in Serum or Plasma
    "ggt": "2324-2",              # Gamma glutamyl transferase in Serum or Plasma
    "gamma_gt": "2324-2",         # legacy key for GGT
    "alp": "6768-6",              # Alkaline phosphatase in Serum or Plasma
    "total_bilirubin": "1975-2",  # Bilirubin.total [Mass/volume] in Serum or Plasma
    "direct_bilirubin": "1968-7",  # Bilirubin.direct [Mass/volume] in Serum or Plasma
    # Lipids
    "total_cholesterol": "2093-3",  # Cholesterol [Mass/volume] in Serum or Plasma
    "hdl_cholesterol": "2085-9",    # Cholesterol in HDL in Serum or Plasma
    "ldl_cholesterol": "13457-7",   # Cholesterol in LDL ... by calculation
    "triglycerides": "2571-8",      # Triglyceride [Mass/volume] in Serum or Plasma
    # Iron / proteins
    "serum_iron": "2498-4",       # Iron [Mass/volume] in Serum or Plasma
    "ferritin": "2276-4",         # Ferritin [Mass/volume] in Serum or Plasma
    "transferrin": "3034-6",      # Transferrin [Mass/volume] in Serum or Plasma
    "tibc": "2500-7",             # Iron binding capacity in Serum or Plasma
    "total_protein": "2885-2",    # Protein [Mass/volume] in Serum or Plasma
    "albumin": "1751-7",          # Albumin [Mass/volume] in Serum or Plasma
    # Thyroid / inflammation
    "tsh": "3016-3",              # Thyrotropin [Units/volume] in Serum or Plasma
    "free_t4": "3024-7",          # Thyroxine (T4) free in Serum or Plasma
    "free_t3": "3051-0",          # Triiodothyronine (T3) Free in Serum or Plasma
    "crp": "1988-5",              # C reactive protein [Mass/volume] in Serum or Plasma
}
