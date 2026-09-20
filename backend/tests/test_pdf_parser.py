"""Tests for PDFParser colon-less tabular parsing (real-world Hungarian formats)."""
from __future__ import annotations

from datetime import datetime

import pytest

from ingestion.pdf_parser import PDFParser

FORMAT_A_TEXT = """
1 / 1. oldal
Laboratóriumi lelet
Vizsgálatot végző laboratórium Ellátott személy
Intézmény Név: Teszt Elek
Név: Minta Egészségügyi Szolgálat Azonosító: 111222333 (TAJ)
Azonosító: 999999 (NNGYK)
Születési idő: 1990.01.01
Cím: 1111 Budapest, Minta utca 1.
Nem: férfi
Szervezeti egység Lakcím: 1111 Budapest, Minta utca 1.
Név: Központi Laboratórium
Ellátási esemény
Ellátás időpontja: 2026.06.12 07:23:00 - 2026.06.12 11:40:35
LOINC Vizsgálat Eredmény * Referenciatartomány Státusz
kód (Validáló)
Vérkép
1 6690-2 Fehérvérsejtszám 6.85 G/l 4.00 - 10.00 G/l VALIDÁLT (1)
37 14647-2 Koleszterin 5.4 mmol/l magas 3.9 - 5.2 mmol/l VALIDÁLT (1)
39 14646-4 HDL-koleszterin 1.20 mmol/l alacsony > 1.30 mmol/l VALIDÁLT (1)
36 62238-1 eGFR EPI formula (számított) >90 > 90 ml/perc/1,73m2 VALIDÁLT (1)
45 57751-0 vizelet Hgb-vvt Negatív VALIDÁLT (1)
Mintavétel időpontja: 2026.06.12 07:35:55 Validáló: (1) Minta Validáló Dr. (EESZT: O00001)
Kiadás időpontja: 2026.06.12 11:40:35 Laboratórium: Központi Laboratórium (NNGYK: 000000000, NEAK: 000000000)
MEGJEGYZÉS A LELETHEZ:
A laboratóriumi lelet aláírás nélkül is hiteles, csak teljes terjedelemben másolható.
EESZT által generált dokumentum E000000.THETIS_S20260612-00 (ver.: 1)
"""

FORMAT_B_TEXT = """
Minta Egészségügyi Szolgálat Oldal: 1
Központi Laboratórium
Azonosító _________: 111222333 Típus: 1 (TAJ szám mezõ ki van töltve)
Név _______________: Teszt Elek Nem: Férfi
Szül.idõ __________: 1990.01.01. Sorszám: 5
Cím _______________: [HUN] 1111 Budapest, Minta utca 1.
Megjelent _________: 2025.05.13. 07:05:00
Mintavétel ________: 2025.05.13. 07:12:45
Beküldõ ___________: (000000000) MINTA BT. Dr. Teszt Orvos
Tesztnév Eredmény Egység F Referencia Státusz
Vérkép Valid
Fehérvérsejtszám 6,74 G/l 4,00 - 10,00
Koleszterin 5,3 mmol/l * 3,9 - 5,2 Valid
HDL-koleszterin 1,25 mmol/l * 1,30 - Valid
eGFR EPI formula (számított) >90 ml/perc/1,73m2 90 - Valid
vizelet Hgb-vvt Negatív
Lelet: 5/2025.05.13. Teszt Elek (1990.01.01.) [111222333] Oldal: 2
Tesztnév Eredmény Egység F Referencia Státusz
TSH (thyreoidastimuláló hormon) 1,05 mIU/l 0,50 - 4,78 Valid

2025.05.13. 11:16:24 Validálta: Teszt Validáló
A laboratóriumi lelet aláírás nélkül is hiteles, csak teljes terjedelemben másolható.
"""


@pytest.fixture
def parser() -> PDFParser:
    return PDFParser()


def _by_name(results) -> dict:
    return {r.raw_name: r for r in results}


# ── Format A (EESZT) ─────────────────────────────────────────────────────────

def test_format_a_parses_only_numeric_tabular_rows(parser):
    """Only clean numeric rows parse; inequality and qualitative rows are skipped."""
    results = parser._parse_results(FORMAT_A_TEXT, [])
    names = {r.raw_name for r in results}
    assert names == {"Fehérvérsejtszám", "Koleszterin", "HDL-koleszterin"}
    assert len(results) == 3


def test_format_a_feherversejtszam_range_and_unit(parser):
    """A duplicated trailing unit must not leak into the unit or break the range."""
    r = _by_name(parser._parse_results(FORMAT_A_TEXT, []))["Fehérvérsejtszám"]
    assert r.value == 6.85
    assert r.unit == "G/l"
    assert r.ref_range_low == 4.00
    assert r.ref_range_high == 10.00


def test_format_a_koleszterin_magas_flag(parser):
    r = _by_name(parser._parse_results(FORMAT_A_TEXT, []))["Koleszterin"]
    assert r.value == 5.4
    assert r.is_flagged is True
    assert r.flag_direction == "high"


def test_format_a_hdl_alacsony_open_lower_bound(parser):
    r = _by_name(parser._parse_results(FORMAT_A_TEXT, []))["HDL-koleszterin"]
    assert r.is_flagged is True
    assert r.flag_direction == "low"
    assert r.ref_range_low == 1.30
    assert r.ref_range_high is None


def test_format_a_egfr_inequality_is_skipped(parser):
    results = parser._parse_results(FORMAT_A_TEXT, [])
    assert all("eGFR" not in r.raw_name for r in results)


def test_format_a_sample_date(parser):
    info = parser._parse_patient(FORMAT_A_TEXT, [])
    assert info.sample_date == datetime(2026, 6, 12, 7, 35, 55)


# ── Format B (legacy/Corden) ─────────────────────────────────────────────────

def test_format_b_parses_only_genuine_numeric_rows(parser):
    """Continuation headers and signature lines must not create spurious rows."""
    results = parser._parse_results(FORMAT_B_TEXT, [])
    names = [r.raw_name for r in results]
    assert names == ["Fehérvérsejtszám", "Koleszterin", "HDL-koleszterin", "TSH (thyreoidastimuláló hormon)"]
    assert len(results) == 4


def test_format_b_koleszterin_star_fallback_flag(parser):
    r = _by_name(parser._parse_results(FORMAT_B_TEXT, []))["Koleszterin"]
    assert r.value == 5.3
    assert r.is_flagged is True


def test_format_b_hdl_no_symbol_open_bound(parser):
    r = _by_name(parser._parse_results(FORMAT_B_TEXT, []))["HDL-koleszterin"]
    assert r.ref_range_low == 1.30
    assert r.ref_range_high is None


def test_format_b_tsh_on_continuation_page(parser):
    r = _by_name(parser._parse_results(FORMAT_B_TEXT, []))[
        "TSH (thyreoidastimuláló hormon)"
    ]
    assert r.value == 1.05


def test_format_b_sample_date(parser):
    info = parser._parse_patient(FORMAT_B_TEXT, [])
    assert info.sample_date == datetime(2025, 5, 13, 7, 12, 45)


# ── Sample-date diagnostics ──────────────────────────────────────────────────

def test_missing_sample_date_reports_error(parser):
    errors: list[str] = []
    parser._parse_patient("no sample line here at all", errors)
    assert any("Sample date not found" in e for e in errors)
