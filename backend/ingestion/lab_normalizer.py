"""Lab result name normalisation: Hungarian/Latin → English standard keys."""

from __future__ import annotations


class LabNormalizer:
    """Maps raw lab test names (Hungarian/Latin) to standardised English keys."""

    KNOWN_MAPPINGS: dict[str, str] = {
        # Blood count
        "fehérvérsejt": "wbc",
        "vörösvértest": "rbc",
        "vörösvérsejt": "rbc",
        "hemoglobin": "hemoglobin",
        "haemoglobin": "hemoglobin",
        "hematokrit": "hematocrit",
        "haematokrit": "hematocrit",
        "trombocita": "platelets",
        "thrombocyta": "platelets",
        "limfocita (abszolut)": "lymphocytes_abs",
        "limfocita": "lymphocytes_pct",
        "monocita (abszolut)": "monocytes_abs",
        "monocita": "monocytes_pct",
        "neutrofil (abszolut)": "neutrophils_abs",
        "neutrofil": "neutrophils_pct",
        "eozinofil (abszolut)": "eosinophils_abs",
        "eozinofil": "eosinophils_pct",
        "basofil (abszolut)": "basophils_abs",
        "basofil": "basophils_pct",
        "mcv": "mcv",
        "mch": "mch",
        "mchc": "mchc",
        "mpv": "mpv",
        "we": "esr",
        # Metabolic
        "vércukor": "glucose",
        "glukóz": "glucose",
        "glucose": "glucose",
        "cukor": "glucose",
        "hba1c": "hba1c",
        "karbamid": "bun",
        "urea": "bun",
        "bun": "bun",
        "kreatinin": "creatinine",
        "creatinin": "creatinine",
        "se. creatinin": "creatinine",
        "hugysav": "uric_acid",
        "húgysav": "uric_acid",
        "egfr": "egfr",
        # Liver
        "got": "ast",
        "ast": "ast",
        "ast (got)": "ast",
        "gpt": "alt",
        "alt": "alt",
        "alt (gpt)": "alt",
        "gamma gt": "ggt",
        "gamma-gt": "ggt",
        "gamma_gt": "ggt",
        "alkalikus foszfatáz": "alp",
        "alp": "alp",
        "totál bilirubin": "total_bilirubin",
        "bilirubin": "total_bilirubin",
        "konjugált bilirubin": "direct_bilirubin",
        # Lipids
        "összkoleszterin": "total_cholesterol",
        "koleszterin": "total_cholesterol",
        "triglicerid": "triglycerides",
        "trigliceridek": "triglycerides",
        "hdl koleszterin": "hdl_cholesterol",
        "hdl-koleszterin": "hdl_cholesterol",
        "hdl": "hdl_cholesterol",
        "ldl koleszterin": "ldl_cholesterol",
        "ldl-koleszterin": "ldl_cholesterol",
        "ldl": "ldl_cholesterol",
        # Iron
        "szérum fe": "serum_iron",
        "ferritin": "ferritin",
        "transzferrin": "transferrin",
        "teljes vaskötő kapacitá": "tibc",
        "teljes vaskötő kapacitás": "tibc",
        # Electrolytes
        "szérum na": "sodium",
        "nátrium": "sodium",
        "szérum k": "potassium",
        "kálium": "potassium",
        "szérum ca": "calcium",
        "kalcium": "calcium",
        "szérum mg": "magnesium",
        "magnézium": "magnesium",
        "klorid": "chloride",
        # Proteins
        "fehérje": "total_protein",
        "total_protein": "total_protein",
        "albumin": "albumin",
        # Thyroid
        "tsh": "tsh",
        "tsh (3. generációs)": "tsh",
        "ft4": "free_t4",
        "free_t4": "free_t4",
        "ft3": "free_t3",
        "free_t3": "free_t3",
        # Inflammation
        "c reaktív protein": "crp",
        "crp": "crp",
        # Vitals
        "vérnyomás": "blood_pressure",
        # Urine
        "általános vizelet": "urinalysis",
        "vizelet üledék": "urine_sediment",
    }

    def normalize(self, raw_name: str) -> str:
        """Map a raw test name to a standard key.

        Strategy:
        1. Exact match after lowercasing and stripping.
        2. Partial / substring match.
        3. Return lowercased raw_name as fallback.

        Args:
            raw_name: The test name as it appears in the source document.

        Returns:
            Standardised English key string.
        """
        key = raw_name.lower().strip()

        # 1. Exact match
        if key in self.KNOWN_MAPPINGS:
            return self.KNOWN_MAPPINGS[key]

        # 2. Partial match – find the longest matching prefix/substring
        best_match: str | None = None
        best_len = 0
        for known, standard in self.KNOWN_MAPPINGS.items():
            if known in key and len(known) > best_len:
                best_match = standard
                best_len = len(known)

        if best_match:
            return best_match

        # 3. Fallback
        return key
