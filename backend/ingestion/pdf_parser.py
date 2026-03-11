"""
PDFParser — Hungarian/Latin medical lab result PDF parser.

Handles the Corden-style Hungarian lab PDF format:
  - Mixed Hungarian and Latin test names
  - Hungarian decimal separator (comma → dot)
  - WHO codes
  - Reference ranges: low-high, <value, >value
  - Out-of-range flag (+/-)
  - Grouped test panels (e.g. "Teljes vérkép")
  - Patient metadata extraction
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LabValue:
    """A single parsed lab test result."""
    raw_name: str                        # Exact name from PDF e.g. "Fehérvérsejt"
    normalized_name: str                 # Standard key e.g. "wbc"
    value: float
    unit: str
    ref_range_low: Optional[float]
    ref_range_high: Optional[float]
    ref_range_text: str                  # Raw reference range string from PDF
    is_flagged: bool                     # True if out of range
    flag_direction: Optional[str]        # "high", "low", or None
    who_code: Optional[str]              # WHO code if present e.g. "28014"
    group: Optional[str]                 # Panel group e.g. "Teljes vérkép"


@dataclass
class PatientInfo:
    """Patient metadata extracted from the PDF header."""
    name: Optional[str] = None
    birth_date: Optional[date] = None
    sex: Optional[str] = None           # normalized to "male" / "female"
    taj_number: Optional[str] = None
    sample_date: Optional[datetime] = None
    referring_doctor: Optional[str] = None
    lab_name: Optional[str] = None


@dataclass
class ParsedLabReport:
    """Full parsed result of one lab PDF."""
    patient: PatientInfo
    results: list[LabValue]
    source_filename: str
    parse_errors: list[str] = field(default_factory=list)

    @property
    def flagged_results(self) -> list[LabValue]:
        """Return only out-of-range values."""
        return [r for r in self.results if r.is_flagged]

    def to_dict(self) -> dict:
        """Serialize to plain dict for DB storage or API response."""
        return {
            "patient": {
                "name": self.patient.name,
                "birth_date": self.patient.birth_date.isoformat() if self.patient.birth_date else None,
                "sex": self.patient.sex,
                "taj_number": self.patient.taj_number,
                "sample_date": self.patient.sample_date.isoformat() if self.patient.sample_date else None,
                "referring_doctor": self.patient.referring_doctor,
                "lab_name": self.patient.lab_name,
            },
            "results": [
                {
                    "raw_name": r.raw_name,
                    "normalized_name": r.normalized_name,
                    "value": r.value,
                    "unit": r.unit,
                    "ref_range_low": r.ref_range_low,
                    "ref_range_high": r.ref_range_high,
                    "ref_range_text": r.ref_range_text,
                    "is_flagged": r.is_flagged,
                    "flag_direction": r.flag_direction,
                    "who_code": r.who_code,
                    "group": r.group,
                }
                for r in self.results
            ],
            "source_filename": self.source_filename,
            "parse_errors": self.parse_errors,
        }


# ---------------------------------------------------------------------------
# Name normalizer — Hungarian/Latin to standard internal keys
# ---------------------------------------------------------------------------

KNOWN_MAPPINGS: dict[str, str] = {
    # Blood count
    "fehérvérsejt": "wbc",
    "vörösvértest": "rbc",
    "vörösvérsejt": "rbc",
    "hemoglobin": "hemoglobin",
    "hematokrit": "hematocrit",
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
    "glukóz": "glucose",
    "cukor": "glucose",
    "hba1c": "hba1c",
    "karbamid": "bun",
    "kreatinin": "creatinine",
    "hugysav": "uric_acid",
    "húgysav": "uric_acid",
    "egfr": "egfr",
    # Liver
    "got": "ast",
    "gpt": "alt",
    "gamma gt": "ggt",
    "gamma-gt": "ggt",
    "alkalikus foszfatáz": "alp",
    "totál bilirubin": "total_bilirubin",
    "konjugált bilirubin": "direct_bilirubin",
    # Lipids
    "koleszterin": "total_cholesterol",
    "triglicerid": "triglycerides",
    "hdl koleszterin": "hdl_cholesterol",
    "ldl koleszterin": "ldl_cholesterol",
    "hdl-koleszterin": "hdl_cholesterol",
    "ldl-koleszterin": "ldl_cholesterol",
    # Iron
    "szérum fe": "serum_iron",
    "ferritin": "ferritin",
    "transzferrin": "transferrin",
    "teljes vaskötő kapacitá": "tibc",
    "teljes vaskötő kapacitás": "tibc",
    # Electrolytes
    "szérum na": "sodium",
    "szérum k": "potassium",
    "szérum ca": "calcium",
    "szérum mg": "magnesium",
    # Thyroid
    "tsh": "tsh",
    "ft4": "free_t4",
    "ft3": "free_t3",
    # Inflammation
    "c reaktív protein": "crp",
    "crp": "crp",
    # Urine (text results — skipped during numeric parsing)
    "általános vizelet": "urinalysis",
    "vizelet üledék": "urine_sediment",
}


def normalize_name(raw_name: str) -> str:
    """
    Map a raw Hungarian/Latin lab test name to a standard internal key.
    Falls back to a sanitized version of the raw name if no mapping found.
    """
    cleaned = raw_name.strip().lower()
    if cleaned in KNOWN_MAPPINGS:
        return KNOWN_MAPPINGS[cleaned]
    # Partial match — pick longest matching key
    best_match, best_len = None, 0
    for key, val in KNOWN_MAPPINGS.items():
        if key in cleaned and len(key) > best_len:
            best_match, best_len = val, len(key)
    if best_match:
        return best_match
    # Fallback
    return re.sub(r"[^a-z0-9áéíóöőúüű]", "_", cleaned).strip("_")


# ---------------------------------------------------------------------------
# PDFParser
# ---------------------------------------------------------------------------

class PDFParser:
    """
    Parse Hungarian/Latin medical lab result PDFs into structured data.

    Usage:
        parser = PDFParser()
        report = parser.parse("path/to/lab_result.pdf")

        # Access results
        for result in report.results:
            print(result.raw_name, result.value, result.unit, result.is_flagged)

        # Only flagged (out of range) values
        for result in report.flagged_results:
            print(result.raw_name, result.flag_direction)

        # Full dict for API / DB
        data = report.to_dict()
    """

    _SEPARATOR_RE = re.compile(r"^[\s\-]{10,}$")

    # Group panel header: e.g. "28014 Teljes vérkép Valid"
    _GROUP_HEADER_RE = re.compile(
        r"^\s*\d{4,6}\s+"
        r"([A-ZÁÉÍÓÖŐÚÜŰa-záéíóöőúüű][^\d:]{3,50}?)"
        r"\s*(?:Valid|Invalid)?\s*$"
    )

    # Patient info
    # Note: pdfplumber extracts two-column header as separate lines.
    # The name appears on a line BEFORE "Név : Sorszám _:" labels,
    # formatted as "Firstname Lastname <sorszam_number>"
    _NAME_LABEL_RE = re.compile(r"^Név\s*:\s*Sorszám", re.IGNORECASE | re.MULTILINE)
    _BIRTH_RE = re.compile(r"Született[:\s]+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
    _SEX_RE = re.compile(r"Nem\s*[_\s]*:\s*(Férfi|Nő|férfi|nő)", re.IGNORECASE)
    _TAJ_RE = re.compile(r"TAJ szám\s*:\s*(\d[\d\s]+\d)", re.IGNORECASE)
    _SAMPLE_DATE_RE = re.compile(
        r"Mintavétel ideje\s*[_\s]*:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})",
        re.IGNORECASE,
    )
    _DOCTOR_RE = re.compile(
        r"Beküldő\s*:\s*\(\d+\)\s*(.+)$", re.IGNORECASE | re.MULTILINE
    )

    # Lines to always skip
    _SKIP_KEYWORDS = {
        "telefon", "http", "www", "email", "fax",
        "beküldő", "orvos", "laborba", "validálva",
        "archiválva", "összpont", "mintavétel",
        "laborbaérkezés", "jogviszony", "előző",
        "taj szám", "típus", "sorszám", "lakáscím",
        "tart.cím", "született", "megjegyz",
    }

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def parse(self, file_path: str | Path) -> ParsedLabReport:
        """
        Parse a Hungarian lab result PDF.

        Args:
            file_path: path to the PDF file.

        Returns:
            ParsedLabReport containing patient info, all LabValues, and any errors.
        """
        file_path = Path(file_path)
        errors: list[str] = []

        try:
            text = self._extract_text(file_path)
        except Exception as exc:
            logger.error(f"Text extraction failed for {file_path}: {exc}")
            return ParsedLabReport(
                patient=PatientInfo(),
                results=[],
                source_filename=file_path.name,
                parse_errors=[f"Text extraction failed: {exc}"],
            )

        patient = self._parse_patient(text, errors)
        results = self._parse_results(text, errors)

        logger.info(
            f"{file_path.name}: {len(results)} results parsed, "
            f"{sum(1 for r in results if r.is_flagged)} flagged"
        )
        return ParsedLabReport(
            patient=patient,
            results=results,
            source_filename=file_path.name,
            parse_errors=errors,
        )

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    def _extract_text(self, file_path: Path) -> str:
        pages = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text(x_tolerance=2, y_tolerance=3)
                if text:
                    pages.append(text)
                else:
                    logger.warning(f"Page {i+1} yielded no text")
        return "\n".join(pages)

    # ------------------------------------------------------------------
    # Patient info
    # ------------------------------------------------------------------

    def _parse_patient(self, text: str, errors: list[str]) -> PatientInfo:
        info = PatientInfo()

        # Name: find the line just before the "Név : Sorszám" label line.
        # pdfplumber may extract spaced characters ("S z a r k a") due to PDF kerning —
        # we detect and collapse this automatically.
        label_m = self._NAME_LABEL_RE.search(text)
        if label_m:
            before = text[:label_m.start()]
            prev_lines = [l.strip() for l in before.splitlines() if l.strip()]
            if prev_lines:
                candidate = prev_lines[-1]
                # Collapse "S z a r k a E d e 7 1 0 8" → "SzarkaEde7108"
                tokens = candidate.split()
                if tokens and all(len(t) == 1 for t in tokens):
                    candidate = "".join(tokens)
                # Strip trailing sorszám number (digits at end)
                name_candidate = re.sub(r"\d+$", "", candidate).strip()
                if name_candidate and len(name_candidate) > 2:
                    info.name = name_candidate

        m = self._BIRTH_RE.search(text)
        if m:
            try:
                info.birth_date = date.fromisoformat(m.group(1))
            except ValueError:
                errors.append(f"Bad birth date: {m.group(1)}")

        m = self._SEX_RE.search(text)
        if m:
            info.sex = "male" if m.group(1).lower() == "férfi" else "female"

        m = self._TAJ_RE.search(text)
        if m:
            info.taj_number = re.sub(r"\s+", "", m.group(1))

        m = self._SAMPLE_DATE_RE.search(text)
        if m:
            try:
                info.sample_date = datetime.strptime(m.group(1).strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                errors.append(f"Bad sample date: {m.group(1)}")

        m = self._DOCTOR_RE.search(text)
        if m:
            info.referring_doctor = m.group(1).strip()

        first_line = text.strip().splitlines()[0].strip()
        if first_line:
            info.lab_name = first_line

        return info

    # ------------------------------------------------------------------
    # Lab result parsing
    # ------------------------------------------------------------------

    def _parse_results(self, text: str, errors: list[str]) -> list[LabValue]:
        results: list[LabValue] = []
        current_group: Optional[str] = None

        for line in text.splitlines():
            stripped = line.strip()

            # Skip empty and separator lines
            if not stripped or self._SEPARATOR_RE.match(stripped):
                continue

            # Skip header/metadata lines
            if any(kw in stripped.lower() for kw in self._SKIP_KEYWORDS):
                continue

            # Detect panel group header (has WHO code, no colon, ends with Valid or is just a name)
            if ":" not in stripped:
                gm = self._GROUP_HEADER_RE.match(line)
                if gm:
                    current_group = gm.group(1).strip()
                continue

            # Parse as result line
            lv = self._parse_line(line, current_group, errors)
            if lv is not None:
                results.append(lv)

        return results

    def _parse_line(
        self,
        line: str,
        group: Optional[str],
        errors: list[str],
    ) -> Optional[LabValue]:
        """Parse one result line. Returns LabValue or None."""

        # Extract optional WHO code at line start
        who_code: Optional[str] = None
        who_m = re.match(r"^\s*(\d{4,6})\s+", line)
        if who_m:
            who_code = who_m.group(1)

        # Split name / value on first colon
        colon_idx = line.index(":")
        name_raw = line[:colon_idx].strip()
        value_raw = line[colon_idx + 1:].strip()

        # Strip WHO code from name
        if who_code:
            name_raw = re.sub(r"^\d{4,6}\s+", "", name_raw).strip()

        if not name_raw or len(name_raw) < 2:
            return None

        # Parse numeric value + unit + reference range + flag
        parsed = self._parse_value_section(value_raw, errors)
        if parsed is None:
            return None

        value, unit, ref_low, ref_high, ref_text, is_flagged, flag_dir = parsed

        return LabValue(
            raw_name=name_raw,
            normalized_name=normalize_name(name_raw),
            value=value,
            unit=unit,
            ref_range_low=ref_low,
            ref_range_high=ref_high,
            ref_range_text=ref_text,
            is_flagged=is_flagged,
            flag_direction=flag_dir,
            who_code=who_code,
            group=group,
        )

    def _parse_value_section(
        self,
        section: str,
        errors: list[str],
    ) -> Optional[tuple]:
        """
        Parse the right-hand side of a colon in a result line.

        Handles:
          "5,72 G/L 4,00 - 10,00"       → value=5.72, unit="G/L", low=4.0, high=10.0
          "0,804 mIU/l 0,400 - 4,000"   → value=0.804, unit="mIU/l"
          "128 U/L 98 - 300 Valid"       → strips "Valid"
          "1,62 mg/L 0,10 - 5,00"       → standard range
          "6,74 mmol/L + 2,50 - 6,60"   → flag "+" before range (some labs)
          "4,0 umol/L + < 3,4"          → high flag, upper-only range
          "Neg Ery/ul"                   → skipped (non-numeric)
          "5 mm/h 3 - 15 Valid"          → integer value
          "79 Valid"                     → value only, no unit/range
          "< 0,10"                       → upper-only range, no unit

        Returns:
            (value, unit, ref_low, ref_high, ref_text, is_flagged, flag_direction)
        """
        section = section.strip()
        if not section:
            return None

        # Remove trailing "Valid" / "Invalid"
        section = re.sub(r"\s*\b(Valid|Invalid)\b\s*$", "", section, flags=re.IGNORECASE).strip()

        # Skip non-numeric text values (Neg, Pos, etc.)
        if re.match(r"^(Neg|Pos|negatív|pozitív|Nincs)\b", section, re.IGNORECASE):
            return None

        # ---- Detect flag (+ or -) ----------------------------------------
        is_flagged = False
        flag_dir: Optional[str] = None

        # Flag can appear at end OR just after the numeric value (before unit/range)
        # Strip trailing flag first
        trailing_flag = re.search(r"\s+([+\-])\s*$", section)
        if trailing_flag:
            flag_dir = "high" if trailing_flag.group(1) == "+" else "low"
            is_flagged = True
            section = section[: trailing_flag.start()].strip()

        # Flag "+" between value and reference range (e.g. "6,74 mmol/L + 2,50 - 6,60")
        # Only match "+" — never "-" because "-" is the range separator (e.g. "4,00 - 10,00")
        inline_flag = re.search(r"\s+(\+)\s+", section)
        if inline_flag and not is_flagged:
            flag_dir = "high"
            is_flagged = True
            section = section[: inline_flag.start()] + " " + section[inline_flag.end():]
            section = section.strip()

        # ---- Extract numeric value ----------------------------------------
        num_match = re.match(r"^([\d,\.]+)", section)
        if not num_match:
            return None

        try:
            value = float(num_match.group(1).replace(",", "."))
        except ValueError:
            return None

        rest = section[num_match.end():].strip()

        # ---- Extract reference range from rest ----------------------------
        ref_text = ""
        ref_low: Optional[float] = None
        ref_high: Optional[float] = None

        # "low - high" (handles negative lower bound with leading "-")
        rng_m = re.search(r"(-?[\d,\.]+)\s*-\s*([\d,\.]+)\s*$", rest)
        if rng_m:
            ref_text = rng_m.group(0).strip()
            try:
                ref_low = float(rng_m.group(1).replace(",", "."))
                ref_high = float(rng_m.group(2).replace(",", "."))
            except ValueError:
                errors.append(f"Could not parse range: {ref_text}")
            rest = rest[: rng_m.start()].strip()

        # "< value"  (upper-only)
        lt_m = re.search(r"<\s*([\d,\.]+)\s*$", rest)
        if lt_m and not rng_m:
            ref_text = lt_m.group(0).strip()
            try:
                ref_high = float(lt_m.group(1).replace(",", "."))
            except ValueError:
                pass
            rest = rest[: lt_m.start()].strip()

        # "> value" (lower-only)
        gt_m = re.search(r">\s*([\d,\.]+)\s*$", rest)
        if gt_m and not rng_m and not lt_m:
            ref_text = gt_m.group(0).strip()
            try:
                ref_low = float(gt_m.group(1).replace(",", "."))
            except ValueError:
                pass
            rest = rest[: gt_m.start()].strip()

        # ---- Auto-flag if outside range (backup for PDFs without + marker) -
        if not is_flagged:
            if ref_low is not None and value < ref_low:
                is_flagged, flag_dir = True, "low"
            elif ref_high is not None and value > ref_high:
                is_flagged, flag_dir = True, "high"

        # ---- Whatever remains is the unit --------------------------------
        unit = rest.strip()

        return value, unit, ref_low, ref_high, ref_text, is_flagged, flag_dir


# ---------------------------------------------------------------------------
# CLI — test directly:  python pdf_parser.py path/to/file.pdf [--json]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python pdf_parser.py <path_to_pdf> [--json]")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    report = PDFParser().parse(sys.argv[1])

    print(f"\n{'='*60}")
    print(f"Lab:       {report.patient.lab_name}")
    print(f"Patient:   {report.patient.name}")
    print(f"DOB:       {report.patient.birth_date}  |  Sex: {report.patient.sex}")
    print(f"Sample:    {report.patient.sample_date}")
    print(f"Doctor:    {report.patient.referring_doctor}")
    print(f"{'='*60}")
    print(f"Results:   {len(report.results)} total  |  {len(report.flagged_results)} flagged")
    print(f"{'='*60}\n")

    if report.flagged_results:
        print("⚠️  OUT OF RANGE:")
        for r in report.flagged_results:
            direction = "HIGH ↑" if r.flag_direction == "high" else "LOW ↓"
            print(
                f"  {r.raw_name:<40} {r.value} {r.unit:<12}"
                f"  ref: {r.ref_range_text:<20} [{direction}]"
            )
        print()

    print("ALL RESULTS:")
    current_group = None
    for r in report.results:
        if r.group != current_group:
            current_group = r.group
            if current_group:
                print(f"\n  [{current_group}]")
        flag = "  ⚠️" if r.is_flagged else ""
        print(
            f"    {r.normalized_name:<28} {r.raw_name:<40}"
            f" = {r.value} {r.unit}{flag}"
        )

    if report.parse_errors:
        print(f"\nParse warnings: {report.parse_errors}")

    if "--json" in sys.argv:
        print("\n--- JSON ---")
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str))
