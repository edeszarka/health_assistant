"""Answer-quality eval for the chat model: faithfulness, expected facts, language.

Run inside the backend container (needs Ollama, not the database):

    python -m eval.answer_eval --model qwen2.5:3b --repeat 3
    python -m eval.answer_eval --model llama3.2:3b --repeat 3 --json /tmp/llama.json
    python -m eval.answer_eval --model qwen2.5:3b --case ldl_lookup   # one case
    python -m eval.answer_eval --model qwen2.5:3b --lang en --cold    # worst-case latency
    python -m eval.answer_eval --rescore /tmp/llama.json --json /tmp/llama2.json  # after a scorer fix

Answers vary between runs (the chat's default sampling is used on purpose),
so compare models with ``--repeat 3``. The JSON output keeps each answer, so a
failure can be reviewed; the answers contain only fictional data.

Each case in ``answer_cases.json`` gives a question and FICTIONAL context
(labs, blood pressure, profile, scores). The real system prompt is built by
``LLMService`` exactly as in the chat, with the case's context instead of
database data, and the answer is scored by the deterministic checks in
``eval.answer_scoring``. English cases decide; Hungarian cases are reported
separately for information. Prints only the fictional case content.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from eval.answer_scoring import (
    contains_expected,
    contains_forbidden,
    has_disclaimer,
    invented_numbers,
    language_ok,
    says_not_available,
)
from services.llm_service import _BASE_PROMPT, ChatResult, LLMService

CASES_PATH = Path(__file__).with_name("answer_cases.json")
LANGUAGE_NAMES = {"en": "English", "hu": "Hungarian"}
_TEXT_KEYS = (
    "flagged_values", "bp_summary", "family_history_summary",
    "health_metrics_summary", "rag_context", "reference_context",
)


@dataclass
class CaseResult:
    """The outcome of one case run."""

    case_id: str
    lang: str
    passed: bool
    missing: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    language_ok: bool = True
    not_available_ok: bool = True
    disclaimer: bool = False
    seconds: Optional[float] = None
    completion_tokens: Optional[int] = None
    reply: str = ""  # fictional-data answer, kept for reviewing failures
    prompt_tokens: Optional[int] = None
    prompt_seconds: Optional[float] = None
    completion_seconds: Optional[float] = None


def load_cases(path: Path = CASES_PATH) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return ``(base_context, cases)`` from the cases file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["base_context"], data["cases"]


def case_context(base: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """The base context with the case's overrides applied."""
    return {**base, **case.get("context", {})}


def sources_for(context: dict[str, Any], question: str) -> list[str]:
    """Every text the model receives, for the invented-number check."""
    texts = [question, _BASE_PROMPT]
    texts += [str(context.get(key, "")) for key in _TEXT_KEYS]
    texts.append(json.dumps(context.get("risk_scores", {})))
    texts.append(json.dumps(context.get("profile", {})))
    return texts


def score_case(case: dict[str, Any], context: dict[str, Any], result: ChatResult) -> CaseResult:
    """Apply every check to one answer."""
    answer = result.reply
    scored = CaseResult(
        case_id=case["id"],
        lang=case["lang"],
        passed=False,
        missing=contains_expected(answer, case.get("contains", [])),
        forbidden=contains_forbidden(answer, case.get("absent", [])),
        invented=invented_numbers(answer, sources_for(context, case["question"])),
        language_ok=language_ok(answer, case["lang"]),
        not_available_ok=says_not_available(answer) if case.get("not_available") else True,
        disclaimer=has_disclaimer(answer),
        seconds=result.total_seconds,
        completion_tokens=result.completion_tokens,
        reply=answer,
        prompt_tokens=result.prompt_tokens,
        prompt_seconds=result.prompt_seconds,
        completion_seconds=result.completion_seconds,
    )
    scored.passed = not (scored.missing or scored.forbidden or scored.invented) and (
        scored.language_ok and scored.not_available_ok
    )
    return scored


def cold_prefix() -> str:
    """A unique first line, so Ollama cannot reuse a cached prompt prefix.

    All cases share most of their context, so without it the system prompt is
    mostly served from Ollama's prompt cache and the latency is optimistic.
    """
    return f"[eval run {uuid.uuid4().hex}]\n"


async def run_case(
    service: LLMService, base: dict[str, Any], case: dict[str, Any], cold: bool = False
) -> CaseResult:
    """Ask the model one case and score the answer.

    Args:
        service: The LLM client for the model under test.
        base: Shared fictional context.
        case: The case to run.
        cold: Defeat Ollama's prompt cache, measuring worst-case latency.
    """
    context = case_context(base, case)
    result = await service.chat_with_stats(
        message=case["question"],
        conversation_history=[],
        context=context.get("rag_context", ""),
        user_profile=SimpleNamespace(**context.get("profile", {})),
        risk_scores=context.get("risk_scores", {}),
        user_language=LANGUAGE_NAMES[case["lang"]],
        health_metrics_summary=context.get("health_metrics_summary", ""),
        flagged_values=context.get("flagged_values", ""),
        bp_summary=context.get("bp_summary", ""),
        family_history_summary=context.get("family_history_summary", ""),
        reference_context=context.get("reference_context", ""),
        system_prefix=cold_prefix() if cold else "",
    )
    return score_case(case, context, result)


def rescore(saved: dict[str, Any], base: dict[str, Any], cases: list[dict[str, Any]]) -> list[CaseResult]:
    """Score the answers saved by ``--json`` again, without calling the model.

    Used after a scorer fix: the answers stay the same, only the checks change.
    """
    by_id = {case["id"]: case for case in cases}
    results = []
    for old in saved["results"]:
        case = by_id[old["case_id"]]
        stats = ChatResult(old["reply"], None, old.get("completion_tokens"), old.get("seconds"))
        results.append(score_case(case, case_context(base, case), stats))
    return results


def _rate(results: list[CaseResult], attr: str) -> float:
    return sum(bool(getattr(r, attr)) for r in results) / len(results)


def summarize(results: list[CaseResult], lang: str) -> dict[str, Any]:
    """Aggregate the results of one language."""
    subset = [r for r in results if r.lang == lang]
    if not subset:
        return {}
    seconds = sorted(r.seconds for r in subset if r.seconds is not None)
    return {
        "cases": len(subset),
        "pass_rate": _rate(subset, "passed"),
        "expected_facts": sum(not r.missing for r in subset) / len(subset),
        "with_invented_number": sum(bool(r.invented) for r in subset) / len(subset),
        "language_ok": _rate(subset, "language_ok"),
        "not_available_ok": _rate(subset, "not_available_ok"),
        "disclaimer": _rate(subset, "disclaimer"),
        "median_seconds": statistics.median(seconds) if seconds else None,
        "p90_seconds": seconds[int(0.9 * (len(seconds) - 1))] if seconds else None,
        **_speed(subset),
    }


def _speed(results: list[CaseResult]) -> dict[str, Any]:
    """Median prompt size and reading/generation speed, where Ollama reported them."""
    prompts = [r.prompt_tokens for r in results if r.prompt_tokens]
    reading = [r.prompt_tokens / r.prompt_seconds for r in results
               if r.prompt_tokens and r.prompt_seconds]
    writing = [r.completion_tokens / r.completion_seconds for r in results
               if r.completion_tokens and r.completion_seconds]
    return {
        "median_prompt_tokens": statistics.median(prompts) if prompts else None,
        "prompt_tokens_per_s": statistics.median(reading) if reading else None,
        "completion_tokens_per_s": statistics.median(writing) if writing else None,
    }


def _print(model: str, results: list[CaseResult]) -> None:
    print(f"model: {model}")
    print("case | lang | pass | missing | forbidden | invented | lang ok | n/a ok | disclaimer | s")
    for r in results:
        secs = f"{r.seconds:.0f}" if r.seconds is not None else "-"
        print(f"{r.case_id} | {r.lang} | {'PASS' if r.passed else 'fail'} | "
              f"{','.join(r.missing) or '-'} | {','.join(r.forbidden) or '-'} | "
              f"{','.join(r.invented) or '-'} | {r.language_ok} | {r.not_available_ok} | "
              f"{r.disclaimer} | {secs}")
    for lang in ("en", "hu"):
        summary = summarize(results, lang)
        if summary:
            label = "decides" if lang == "en" else "information only"
            print(f"{lang} ({label}): " + json.dumps(summary, default=lambda v: round(v, 3)))


async def main(
    model: Optional[str], repeat: int, json_path: Optional[str],
    only: Optional[list[str]] = None, rescore_path: Optional[str] = None,
    lang: Optional[str] = None, cold: bool = False,
) -> None:
    base, cases = load_cases()
    if rescore_path:
        saved = json.loads(Path(rescore_path).read_text(encoding="utf-8"))
        model = saved["model"]
        results = rescore(saved, base, cases)
    else:
        if only:
            cases = [case for case in cases if case["id"] in only]
        if lang:
            cases = [case for case in cases if case["lang"] == lang]
        service = LLMService(model=model)
        results = [
            await run_case(service, base, case, cold) for _ in range(repeat) for case in cases
        ]
    _print(str(model), results)
    if json_path:
        Path(json_path).write_text(
            json.dumps({"model": model, "results": [asdict(r) for r in results],
                        "summary": {lang: summarize(results, lang) for lang in ("en", "hu")}},
                       indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument("--model", help="Ollama model name, e.g. qwen2.5:3b")
    cli.add_argument("--repeat", type=int, default=1, help="runs per case (sampling varies)")
    cli.add_argument("--json", dest="json_path", help="write results (with answers) to this file")
    cli.add_argument("--case", action="append", dest="only", help="run only this case id (repeatable)")
    cli.add_argument("--rescore", dest="rescore_path",
                     help="re-score the answers in a saved --json file; no model call")
    cli.add_argument("--lang", choices=("en", "hu"), help="run only cases in this language")
    cli.add_argument("--cold", action="store_true",
                     help="defeat Ollama's prompt cache to measure worst-case latency")
    args = cli.parse_args()
    if not (args.model or args.rescore_path):
        cli.error("--model or --rescore is required")
    asyncio.run(main(args.model, args.repeat, args.json_path, args.only,
                     args.rescore_path, args.lang, args.cold))
