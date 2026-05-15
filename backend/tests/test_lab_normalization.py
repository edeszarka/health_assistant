"""Tests for LabNormalizer and PDFParser integration."""
from __future__ import annotations

import pytest
from ingestion.lab_normalizer import LabNormalizer

def test_lab_normalizer_exact_match():
    norm = LabNormalizer()
    assert norm.normalize("Vércukor") == "glucose"
    assert norm.normalize("fehérvérsejt") == "wbc"
    assert norm.normalize("TSH (3. generációs)") == "tsh"

def test_lab_normalizer_partial_match():
    norm = LabNormalizer()
    # "se. creatinin" should match "creatinine"
    assert norm.normalize("se. creatinin 102 umol/L") == "creatinine"
    assert norm.normalize("vizelet üledék vizsgálat") == "urine_sediment"

def test_lab_normalizer_fallback():
    norm = LabNormalizer()
    assert norm.normalize("Unknown Test Name") == "unknown test name"

def test_lab_normalizer_categorized_mappings():
    norm = LabNormalizer()
    # Check some categorized mappings merged from pdf_parser.py
    assert norm.normalize("limfocita (abszolut)") == "lymphocytes_abs"
    assert norm.normalize("szérum na") == "sodium"
    assert norm.normalize("összkoleszterin") == "total_cholesterol"
