"""Text templates for RAG embeddings.

One template per source type, shared by the upload routers and the
re-embedding script so stored and rebuilt texts never drift apart.

Users ask in Hungarian or English, and the embedding model matches surface
terms strongly, so each text carries the lab report's own (usually Hungarian)
test name next to the normalised key, and both Hungarian and English wording.
"""
from __future__ import annotations

from typing import Optional


def lab_result_text(
    raw_name: str,
    normalized_name: str,
    value: float,
    unit: Optional[str],
    is_flagged: bool,
) -> str:
    """Build the embedded text for one lab result.

    Args:
        raw_name: Test name as printed on the report, e.g. "Koleszterin".
        normalized_name: Normalised key, e.g. "total_cholesterol".
        value: Numeric result.
        unit: Unit as printed on the report, or ``None``.
        is_flagged: Whether the value is outside the reference range.

    Returns:
        A bilingual one-line description of the result.
    """
    status = (
        "Referenciatartományon kívül / out of reference range."
        if is_flagged
        else "Referenciatartományon belül / within reference range."
    )
    reading = f"{value} {unit}" if unit else f"{value}"
    key = normalized_name.replace("_", " ")
    return f"Laboreredmény / lab result: {raw_name} ({key}) = {reading}. {status}"


def family_history_text(
    relation: str, condition: str, age_of_onset: Optional[int]
) -> str:
    """Build the embedded text for one family history entry.

    Args:
        relation: Relative, e.g. "mother" or "anya".
        condition: Condition as entered by the user.
        age_of_onset: Age at onset, or ``None``.

    Returns:
        A bilingual one-line description of the entry.
    """
    onset = (
        f", kezdet / onset: {age_of_onset} éves / years" if age_of_onset else ""
    )
    return f"Családi kórelőzmény / family history: {relation} — {condition}{onset}."
