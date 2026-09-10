"""Tests for chat intent detection — lab keyword coverage."""
from __future__ import annotations

import pytest

from routers.chat import _detect_intent


# Each message pairs a lab keyword with a non-lab intent keyword (steps, weight,
# sleep, ...). The non-lab keyword guarantees that at least one intent matches,
# so the "empty intents -> all intents" fallback does not run and the assertion
# genuinely verifies that the lab keyword itself triggers the "labs" intent.
@pytest.mark.parametrize(
    "message",
    [
        "What's my WBC and my steps?",
        "What's my RBC and my weight?",
        "Check my hemoglobin and sleep",
        "What's my hematocrit and blood pressure?",
        "Are my platelets low and how is my sleep?",
        "What's my glucose and my weight?",
        "What's my HbA1c and my calories?",
        "Is my creatinine normal and my weight?",
        "What is my eGFR and my heart rate?",
        "What's my AST and my steps?",
        "What's my ALT and my weight?",
        "What's my GGT and my steps?",
        "What's my ALP and my weight?",
        "What's my bilirubin and my steps?",
        "What's my HDL and my weight?",
        "What's my LDL and my steps?",
        "What are my triglycerides and my weight?",
        "What's my ferritin and my sleep?",
        "Is my CRP high and my weight?",
        "What is my TSH and my steps?",
        "What's my free T4 and my weight?",
        "Mennyi a GOT értékem és a testsúlyom?",
        "Mennyi a GPT értékem és a lépéseim?",
        "Mi a TSH-m és a testsúlyom?",
        "Mennyi a karbamid és a testsúlyom?",
        "Mi a vércukor szintem és a súlyom?",
    ],
)
def test_lab_keyword_triggers_labs_intent(message: str) -> None:
    """A recognizable lab keyword should yield the 'labs' intent."""
    assert "labs" in _detect_intent(message)
