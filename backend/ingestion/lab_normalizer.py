"""Lab result name normalisation: Hungarian/Latin → English standard keys."""
from __future__ import annotations


class LabNormalizer:
    """Maps raw lab test names (Hungarian/Latin) to standardised English keys."""

    KNOWN_MAPPINGS: dict[str, str] = {
        "vércukor": "glucose",
        "haemoglobin": "hemoglobin",
        "hemoglobin": "hemoglobin",
        "thrombocyta": "platelets",
        "se. creatinin": "creatinine",
        "creatinin": "creatinine",
        "tsh": "tsh",
        "összkoleszterin": "total_cholesterol",
        "koleszterin": "total_cholesterol",
        "hdl-koleszterin": "hdl_cholesterol",
        "hdl": "hdl_cholesterol",
        "ldl-koleszterin": "ldl_cholesterol",
        "ldl": "ldl_cholesterol",
        "triglicerid": "triglycerides",
        "fehérvérsejt": "wbc",
        "vörösvérsejt": "rbc",
        "hba1c": "hba1c",
        "alt (gpt)": "alt",
        "ast (got)": "ast",
        "húgysav": "uric_acid",
        "ferritin": "ferritin",
        "crp": "crp",
        "bun": "bun",
        "tsh (3. generációs)": "tsh",
        "vérnyomás": "blood_pressure",
        "glukóz": "glucose",
        "glucose": "glucose",
        "urea": "bun",
        "alkalikus foszfatáz": "alp",
        "gamma-gt": "gamma_gt",
        "bilirubin": "bilirubin",
        "nátrium": "sodium",
        "kálium": "potassium",
        "kalcium": "calcium",
        "fehérje": "total_protein",
        "albumin": "albumin",
        "mcv": "mcv",
        "mchc": "mchc",
        "mch": "mch",
        "haematokrit": "hematocrit",
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
