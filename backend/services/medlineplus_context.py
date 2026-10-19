"""Pick MedlinePlus reference texts for a chat question, from the cache only.

The chat never calls MedlinePlus: lab-test texts are prefetched for a fixed
LOINC list by ``scripts.warm_medlineplus``, and a family-history condition is
looked up once when the user saves it with an ICD-10 code. Answering a
question therefore sends nothing about the user off the host (ARCHITECTURE
invariant 4).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ingestion.lab_normalizer import LabNormalizer
from models.db_models import FamilyHistory, LabResult
from services.lab_loinc import LAB_LOINC
from services.medlineplus_service import (
    ICD10_CM_SYSTEM,
    LOINC_SYSTEM,
    connect_cache_key,
    medlineplus_service,
)

logger = logging.getLogger(__name__)

# At most this many reference texts per answer: each is up to
# SUMMARY_MAX_CHARS, and a small chat model loses track of long prompts.
MAX_REFERENCES = 3

# Normaliser terms that are also everyday English words ("we", "got"); they
# would attach unrelated lab references to ordinary sentences.
_AMBIGUOUS_TERMS = frozenset({"we", "got"})
# Terms this short must match a whole word ("alt" not in "alternative");
# longer terms only need a word start, so Hungarian suffixes still match
# ("koleszterinem").
_WHOLE_WORD_MAX_LEN = 4

# Cached summaries are cut at a fixed length, usually mid-sentence. A cut is
# moved back to the last sentence end when one exists in the second half.
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


@dataclass(frozen=True)
class Reference:
    """One MedlinePlus text to put into the prompt."""

    title: str
    summary: str
    url: str


def _term_pattern(term: str) -> re.Pattern[str]:
    """Regex for one lab term inside a message."""
    end = r"\b" if len(term) <= _WHOLE_WORD_MAX_LEN else ""
    return re.compile(r"\b" + re.escape(term) + end)


def _message_terms() -> list[tuple[re.Pattern[str], str]]:
    """(pattern, lab key) for every normaliser term and every lab key."""
    terms = {
        term: key for term, key in LabNormalizer.KNOWN_MAPPINGS.items()
        if term not in _AMBIGUOUS_TERMS
    }
    terms.update({key.replace("_", " "): key for key in LAB_LOINC})
    return [(_term_pattern(term), key) for term, key in terms.items()]


_TERMS = _message_terms()


def mentioned_keys(message: str) -> list[str]:
    """Lab keys named in the message, in order of first appearance."""
    msg = message.lower()
    hits: list[tuple[int, str]] = []
    for pattern, key in _TERMS:
        match = pattern.search(msg)
        if match:
            hits.append((match.start(), key))
    ordered: list[str] = []
    for _, key in sorted(hits):
        if key not in ordered:
            ordered.append(key)
    return ordered


async def _user_lab_keys(db: AsyncSession) -> tuple[set[str], list[str]]:
    """Return the user's lab keys and those whose latest result is flagged."""
    result = await db.execute(
        select(LabResult.test_name, LabResult.is_flagged, LabResult.test_date)
    )
    latest: dict[str, tuple[date, bool]] = {}
    for test_name, is_flagged, test_date in result.fetchall():
        when = test_date or date.min
        if test_name not in latest or when >= latest[test_name][0]:
            latest[test_name] = (when, bool(is_flagged))
    flagged = sorted(key for key, (_, is_flagged) in latest.items() if is_flagged)
    return set(latest), flagged


def choose_keys(mentioned: list[str], user_keys: set[str], flagged: list[str]) -> list[str]:
    """Order candidate keys: mentioned first, then flagged; one per LOINC code.

    Only keys the user has results for and that have a LOINC code count.
    Several codes can share one MedlinePlus page, so the cap is applied
    after pages are de-duplicated (``merge_references``).
    """
    chosen: list[str] = []
    codes: set[str] = set()
    for key in mentioned + flagged:
        code = LAB_LOINC.get(key)
        if key not in user_keys or code is None or code in codes:
            continue
        chosen.append(key)
        codes.add(code)
    return chosen


def trim_to_sentence(text: str) -> str:
    """Cut a truncated summary back to its last complete sentence."""
    ends = [m.end() for m in _SENTENCE_END.finditer(text)]
    if ends and ends[-1] >= len(text) // 2:
        return text[: ends[-1]]
    return text


def merge_references(*groups: list[Reference]) -> list[Reference]:
    """Concatenate reference lists, one per page, capped at ``MAX_REFERENCES``."""
    merged: list[Reference] = []
    urls: set[str] = set()
    for group in groups:
        for ref in group:
            if ref.url in urls:
                continue
            merged.append(ref)
            urls.add(ref.url)
            if len(merged) == MAX_REFERENCES:
                return merged
    return merged


async def _cached_reference(cache_key: str, fallback_title: str, db: AsyncSession) -> Reference | None:
    """Build a reference from the cache, or ``None`` when nothing usable is cached."""
    cached = await medlineplus_service.get_cached(cache_key, db)
    if not cached or not cached.get("url") or not cached.get("summary"):
        logger.info("No cached MedlinePlus text for %s.", cache_key)
        return None
    return Reference(
        cached.get("title") or fallback_title,
        trim_to_sentence(cached["summary"]),
        cached["url"],
    )


async def lab_references(message: str, db: AsyncSession) -> list[Reference]:
    """Return cached MedlinePlus texts for the labs this question is about.

    Args:
        message: The user's chat message.
        db: Async database session.

    Returns:
        Up to ``MAX_REFERENCES`` references; empty when nothing is cached.
    """
    user_keys, flagged = await _user_lab_keys(db)
    references: list[Reference] = []
    urls: set[str] = set()
    for key in choose_keys(mentioned_keys(message), user_keys, flagged):
        cache_key = connect_cache_key(LAB_LOINC[key], LOINC_SYSTEM)
        ref = await _cached_reference(cache_key, key, db)
        if ref is None or ref.url in urls:
            continue
        references.append(ref)
        urls.add(ref.url)
        if len(references) == MAX_REFERENCES:
            break
    return references


async def family_references(db: AsyncSession) -> list[Reference]:
    """Return cached MedlinePlus texts for family-history ICD-10 codes.

    Args:
        db: Async database session.

    Returns:
        One reference per distinct page, newest entry first, capped at
        ``MAX_REFERENCES``; entries without a code or cached text are skipped.
    """
    result = await db.execute(
        select(FamilyHistory.icd10_code)
        .where(FamilyHistory.icd10_code.isnot(None))
        .order_by(FamilyHistory.created_at.desc())
    )
    references: list[Reference] = []
    for (code,) in result.fetchall():
        ref = await _cached_reference(connect_cache_key(code, ICD10_CM_SYSTEM), code, db)
        if ref is not None:
            references.append(ref)
    return merge_references(references)


def format_references(references: list[Reference]) -> str:
    """Render references for the prompt's <reference> block."""
    return "\n\n".join(
        f"{ref.title} ({ref.url}):\n{ref.summary}" for ref in references
    )
