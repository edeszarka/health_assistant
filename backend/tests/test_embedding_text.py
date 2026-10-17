"""Tests for the RAG embedding text templates."""
from __future__ import annotations

from services.embedding_text import family_history_text, lab_result_text


def test_lab_text_keeps_report_name_and_readable_key():
    text = lab_result_text("Koleszterin", "total_cholesterol", 6.1, "mmol/l", True)
    assert "Koleszterin" in text
    assert "total cholesterol" in text
    assert "6.1 mmol/l" in text


def test_lab_text_states_range_in_both_languages():
    flagged = lab_result_text("Glükóz", "glucose", 7.2, "mmol/l", True)
    normal = lab_result_text("Glükóz", "glucose", 5.0, "mmol/l", False)
    assert "kívül" in flagged and "out of reference range" in flagged
    assert "belül" in normal and "within reference range" in normal


def test_lab_text_without_unit_has_no_dangling_none():
    text = lab_result_text("pH", "urine_ph", 6.0, None, False)
    assert "None" not in text
    assert "= 6.0." in text


def test_family_history_text_with_and_without_onset():
    with_onset = family_history_text("anya", "cukorbetegség", 55)
    without = family_history_text("father", "hypertension", None)
    assert "anya" in with_onset and "cukorbetegség" in with_onset and "55" in with_onset
    assert "family history" in without and "hypertension" in without
    assert "onset" not in without
