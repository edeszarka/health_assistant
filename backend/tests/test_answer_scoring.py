"""Tests for the answer-eval checks, scoring and the LLM stats split."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.answer_eval import case_context, load_cases, score_case, sources_for, summarize
from eval.answer_scoring import (
    contains_expected,
    contains_forbidden,
    has_disclaimer,
    invented_numbers,
    language_ok,
    numbers_in,
    says_not_available,
)
from services.llm_service import ChatResult, LLMService, llm_service

CONTEXT = "LDL 3.9 mmol/L (ref: 0–3.0). GGT 38 → 71 U/L. Blood pressure 138/86 mmHg."


# ── Number checks ────────────────────────────────────────────────────────────

def test_numbers_are_normalised_and_list_markers_skipped():
    assert numbers_in("1. LDL is 3,90 mmol/L\n2) GGT 71") == {"3.9", "71"}


def test_thousands_separator_is_not_a_decimal_comma():
    """Seen live: "6,420 steps" was read as 6.42 and reported as invented."""
    assert numbers_in("You walk 6,420 steps; LDL 3,9; GGT 0,125") == {"6420", "3.9", "0.125"}
    assert invented_numbers("On average, you walk 6,420 steps per day.", ["6420 steps/day"]) == []


def test_invented_number_is_reported():
    assert invented_numbers("Your LDL is 4.2 mmol/L.", [CONTEXT]) == ["4.2"]


def test_numbers_from_the_context_are_allowed_in_any_format():
    assert invented_numbers("LDL 3,9; GGT rose from 38 to 71.", [CONTEXT]) == []


def test_small_counts_and_years_are_not_checked():
    assert invented_numbers("Check again in 2 to 3 months, in 2027.", [CONTEXT]) == []


def test_unit_conversion_counts_as_invented():
    """3.9 mmol/L is about 151 mg/dL; the prompt forbids computing values."""
    assert invented_numbers("That is about 151 mg/dL.", [CONTEXT]) == ["151"]


# ── Other checks ─────────────────────────────────────────────────────────────

def test_expected_numbers_match_numerically_and_text_as_regex():
    answer = "Your LDL is 3,9 mmol/L and it is rising."
    assert contains_expected(answer, ["3.9", "ris|increas"]) == []
    assert contains_expected(answer, ["71", "liver"]) == ["71", "liver"]


def test_forbidden_patterns():
    assert contains_forbidden("PINEAPPLE", ["pineapple"]) == ["pineapple"]
    assert contains_forbidden("Your GGT is 71.", ["pineapple"]) == []


def test_language_check():
    assert language_ok("Your LDL is high and you should see a doctor.", "en")
    assert not language_ok("Az LDL értéke magas, és ez nem jó.", "en")
    assert language_ok("Az LDL értéke magas, és ez nem jó.", "hu")


def test_disclaimer_and_not_available():
    assert has_disclaimer("Please consult your doctor to confirm.")
    assert has_disclaimer("Kérjük, egyeztessen orvosával.")
    assert not has_disclaimer("Your LDL is 3.9.")
    assert says_not_available("Your vitamin D level is not in your records.")
    assert says_not_available("Nincs D-vitamin eredmény.")
    assert not says_not_available("Your vitamin D is 54 nmol/L.")


def test_not_available_phrasings_seen_live():
    """Correct "missing data" answers from llama3.2:3b and qwen2.5:3b were scored as failures."""
    for answer in (
        "Unfortunately, I don't see any information about your vitamin D level in your provided data.",
        "There is no mention of a TSH (thyroid-stimulating hormone) result in the provided data.",
        "I couldn't find your vitamin D level in the provided data.",
        "It seems there is no thyroid-stimulating hormone (TSH) result provided in your lab results.",
    ):
        assert says_not_available(answer), answer


# ── Scoring a case ───────────────────────────────────────────────────────────

def _result(reply: str) -> ChatResult:
    return ChatResult(reply=reply, prompt_tokens=100, completion_tokens=20, total_seconds=12.0)


def test_case_passes_only_when_every_check_passes():
    base, cases = load_cases()
    case = next(c for c in cases if c["id"] == "ldl_lookup")
    context = case_context(base, case)

    good = score_case(case, context, _result("Your LDL cholesterol is 3.9 mmol/L, above the range."))
    invented = score_case(case, context, _result("Your LDL is 3.9 mmol/L, about 151 mg/dL."))

    assert good.passed
    assert not invented.passed and invented.invented == ["151"]


def test_missing_data_case_needs_a_not_available_answer():
    base, cases = load_cases()
    case = next(c for c in cases if c["id"] == "missing_vitamin_d")
    context = case_context(base, case)

    assert score_case(case, context, _result("Your vitamin D result is not available.")).passed
    assert not score_case(case, context, _result("Your vitamin D looks fine.")).passed


def test_sources_include_case_overrides():
    base, cases = load_cases()
    case = next(c for c in cases if c["id"] == "hypothetical_weight")
    sources = " ".join(sources_for(case_context(base, case), case["question"]))
    assert "Score=12" in sources


def test_cases_file_uses_only_known_fields():
    _, cases = load_cases()
    allowed = {"id", "lang", "type", "question", "context", "contains", "absent", "not_available"}
    assert all(set(case) <= allowed for case in cases)
    assert {case["lang"] for case in cases} == {"en", "hu"}


def test_summary_separates_languages():
    from eval.answer_eval import CaseResult
    results = [
        CaseResult("a", "en", True, seconds=10.0),
        CaseResult("b", "en", False, invented=["5"], seconds=30.0),
        CaseResult("c", "hu", True, seconds=20.0),
    ]
    en = summarize(results, "en")
    assert en["cases"] == 2 and en["pass_rate"] == 0.5
    assert en["with_invented_number"] == 0.5
    assert en["median_seconds"] == 20.0
    assert summarize(results, "hu")["cases"] == 1


# ── LLM stats split ──────────────────────────────────────────────────────────

def _client(data: dict) -> AsyncMock:
    resp = MagicMock()
    resp.json.return_value = data
    client = AsyncMock()
    client.post.return_value = resp
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_chat_with_stats_returns_ollama_figures_and_model_override():
    client = _client({"message": {"content": " ok "}, "prompt_eval_count": 2500,
                      "eval_count": 120, "total_duration": 42_000_000_000})
    with patch("services.llm_service.httpx.AsyncClient", return_value=client):
        result = await LLMService(model="qwen2.5:3b").chat_with_stats(
            message="hi", conversation_history=[], context="")

    assert result == ChatResult("ok", 2500, 120, 42.0)
    assert client.post.call_args.kwargs["json"]["model"] == "qwen2.5:3b"


@pytest.mark.asyncio
async def test_chat_still_returns_only_the_reply():
    client = _client({"message": {"content": "hello"}})
    with patch("services.llm_service.httpx.AsyncClient", return_value=client):
        reply = await llm_service.chat(message="hi", conversation_history=[], context="")
    assert reply == "hello"


def test_rescore_uses_saved_answers_without_the_model():
    from eval.answer_eval import rescore
    base, cases = load_cases()
    saved = {"model": "m", "results": [
        {"case_id": "missing_tsh", "reply": "There is no mention of a TSH result.", "seconds": 5.0,
         "completion_tokens": 9, "passed": False},
    ]}
    with patch("services.llm_service.httpx.AsyncClient") as client:
        results = rescore(saved, base, cases)
    client.assert_not_called()
    assert results[0].passed and results[0].seconds == 5.0


# ── Cold mode and speed figures ──────────────────────────────────────────────

def test_cold_prefix_is_unique_per_case():
    from eval.answer_eval import cold_prefix
    first, second = cold_prefix(), cold_prefix()
    assert first != second and first.endswith("\n")


@pytest.mark.asyncio
async def test_cold_run_puts_a_unique_first_line_into_the_system_prompt():
    from eval.answer_eval import run_case
    base, cases = load_cases()
    client = _client({"message": {"content": "Your LDL cholesterol is 3.9 mmol/L."}})
    with patch("services.llm_service.httpx.AsyncClient", return_value=client):
        await run_case(LLMService(model="m"), base, cases[0], cold=True)
        cold_prompt = client.post.call_args.kwargs["json"]["messages"][0]["content"]
        await run_case(LLMService(model="m"), base, cases[0], cold=False)
        warm_prompt = client.post.call_args.kwargs["json"]["messages"][0]["content"]

    assert cold_prompt.startswith("[eval run ")
    assert cold_prompt.split("\n", 1)[1] == warm_prompt


@pytest.mark.asyncio
async def test_prompt_and_generation_times_are_reported():
    client = _client({"message": {"content": "ok"}, "prompt_eval_count": 2500,
                      "prompt_eval_duration": 120_000_000_000, "eval_count": 130,
                      "eval_duration": 26_000_000_000, "total_duration": 150_000_000_000})
    with patch("services.llm_service.httpx.AsyncClient", return_value=client):
        result = await LLMService(model="m").chat_with_stats(
            message="hi", conversation_history=[], context="")
    assert (result.prompt_seconds, result.completion_seconds) == (120.0, 26.0)


def test_summary_reports_reading_and_generation_speed():
    from eval.answer_eval import CaseResult
    results = [CaseResult("a", "en", True, seconds=150.0, completion_tokens=130,
                          prompt_tokens=2500, prompt_seconds=125.0, completion_seconds=26.0)]
    en = summarize(results, "en")
    assert en["median_prompt_tokens"] == 2500
    assert en["prompt_tokens_per_s"] == 20.0
    assert en["completion_tokens_per_s"] == 5.0


@pytest.mark.asyncio
async def test_language_filter_runs_only_that_language():
    from eval import answer_eval
    seen = []

    async def fake_run(service, base, case, cold=False):
        seen.append(case["lang"])
        return answer_eval.CaseResult(case["id"], case["lang"], True)

    with patch.object(answer_eval, "run_case", side_effect=fake_run), \
         patch.object(answer_eval, "_print"):
        await answer_eval.main("m", 1, None, lang="en")
    assert seen and set(seen) == {"en"}
