"""Deterministic checks for chat answers, used by ``eval.answer_eval``.

No LLM judge: a small local model is not a reliable grader, and rule-based
checks are reproducible. Each check is a pure function of the answer text.
"""
from __future__ import annotations

import re
from typing import Iterable

# A number in running text: 71, 3.9, 3,9 (Hungarian decimal comma), 6,420
# (English thousands), 85%.
_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?![\d])|\d+(?:[.,]\d+)?)(?![\w])")
# "1." or "2)" at the start of a line is list numbering, not a value.
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
# Small integers (counts, "1-2 times", "10-year") and years carry no
# measured value, so they are not checked for faithfulness.
_SMALL_INT_MAX = 10
_YEAR_RANGE = (1900, 2100)

_EN_STOPWORDS = frozenset(
    "the a an and or is are was were your you of to in for with this that it "
    "be not can your have has on at as by from which what".split()
)
_HU_STOPWORDS = frozenset(
    "a az és vagy is nem van volt hogy egy ez ezt azt meg de ha mint már "
    "csak még kell lehet az ön önnek önt vagyis tehát pedig".split()
)

_DISCLAIMER = re.compile(r"consult (your|a) (doctor|physician)|orvos", re.IGNORECASE)
_NOT_AVAILABLE = re.compile(
    r"not (available|found|recorded|listed|provided|included|in (your|the) "
    r"(records|data|results))"
    r"|no (data|record|records|result|results|information|value|measurement)"
    r"|(do not|don't|does not|doesn't) (have|show|include|contain)"
    r"|(is|are)n't (available|listed|recorded)"
    r"|nincs|nem áll rendelkezésre|nem található|nem szerepel",
    re.IGNORECASE,
)


# "6,420" is an English thousands separator, not the Hungarian decimal comma
# ("3,9"): a comma followed by exactly three digits, not after a leading 0.
_THOUSANDS = re.compile(r"[1-9]\d{0,2}(?:,\d{3})+")


def normalize_number(text: str) -> str:
    """Canonical form of a number: decimal point, no trailing zeros."""
    if _THOUSANDS.fullmatch(text):
        text = text.replace(",", "")
    value = float(text.replace(",", "."))
    return f"{value:g}"


def numbers_in(text: str) -> set[str]:
    """All numbers in ``text``, normalised; list markers are skipped."""
    cleaned = _LIST_MARKER.sub(" ", text)
    return {normalize_number(match) for match in _NUMBER.findall(cleaned)}


def _is_exempt(number: str) -> bool:
    value = float(number)
    if value.is_integer() and value <= _SMALL_INT_MAX:
        return True
    return value.is_integer() and _YEAR_RANGE[0] <= value <= _YEAR_RANGE[1]


def invented_numbers(answer: str, sources: Iterable[str]) -> list[str]:
    """Numbers in the answer that appear in none of the sources.

    The sources are everything the model was given (context blocks, prompt
    template, question). A number found nowhere in them was invented or
    computed by the model, which the prompt forbids for health values.

    Args:
        answer: The model's reply.
        sources: Texts the model received.

    Returns:
        The offending numbers, sorted; empty when the answer is faithful.
    """
    known: set[str] = set()
    for source in sources:
        known |= numbers_in(source)
    return sorted(n for n in numbers_in(answer) - known if not _is_exempt(n))


def contains_expected(answer: str, expected: Iterable[str]) -> list[str]:
    """Expected items missing from the answer.

    A numeric item matches a number in the answer (so "3,9" matches "3.9");
    any other item is a case-insensitive regular expression.
    """
    found_numbers = numbers_in(answer)
    missing = []
    for item in expected:
        if re.fullmatch(r"\d+(?:[.,]\d+)?", item):
            if normalize_number(item) not in found_numbers:
                missing.append(item)
        elif not re.search(item, answer, re.IGNORECASE):
            missing.append(item)
    return missing


def contains_forbidden(answer: str, forbidden: Iterable[str]) -> list[str]:
    """Forbidden patterns (case-insensitive regular expressions) found in the answer."""
    return [item for item in forbidden if re.search(item, answer, re.IGNORECASE)]


def language_ok(answer: str, lang: str) -> bool:
    """Whether the answer is mostly in ``lang`` ("en" or "hu"), by stopwords."""
    words = re.findall(r"[a-záéíóöőúüű']+", answer.lower())
    english = sum(word in _EN_STOPWORDS for word in words)
    hungarian = sum(word in _HU_STOPWORDS for word in words)
    return english > hungarian if lang == "en" else hungarian > english


def has_disclaimer(answer: str) -> bool:
    """Whether the answer tells the user to consult a doctor."""
    return bool(_DISCLAIMER.search(answer))


def says_not_available(answer: str) -> bool:
    """Whether the answer says the requested data is not available."""
    return bool(_NOT_AVAILABLE.search(answer))
