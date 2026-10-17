"""Retrieval eval for the RAG store: recall, precision and false positives.

Run inside the backend container against the live database:

    python -m eval.retrieval_eval

Relevance is decided by metadata (source_type, lab_results.test_name), never
by content, and the report prints only aggregates, so no health values leave
the database. Uses the same embedding call and distance as RAGService and
marks the operating point configured in Settings (rag_top_k,
rag_similarity_threshold).
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.connection import AsyncSessionLocal
from models.db_models import Embedding, LabResult
from services.rag_service import rag_service

QUERIES_PATH = Path(__file__).with_name("queries.json")
MAX_K = 5  # hits fetched per query; every k below is a prefix of these
K_VALUES = (1, 2, 3, 5)
THRESHOLDS = (0.55, 0.60, 0.62, 0.65, 0.70)


@dataclass
class Hit:
    similarity: float
    relevant: bool


async def _top_hits(db: AsyncSession, query: str, label: dict | None) -> list[Hit]:
    """Top hits for a query, each marked relevant/irrelevant against its label."""
    vector = await rag_service.embed_text(query, task="query")
    distance = Embedding.embedding.cosine_distance(vector)
    stmt = (
        select(Embedding.source_type, LabResult.test_name, distance)
        .outerjoin(
            LabResult,
            and_(Embedding.source_type == "lab_result", LabResult.id == Embedding.source_id),
        )
        .order_by(distance)
        .limit(MAX_K)
    )
    hits = []
    for source_type, test_name, dist in (await db.execute(stmt)).all():
        relevant = bool(label) and source_type == label["source_type"] and (
            "test_names" not in label or test_name in label["test_names"]
        )
        hits.append(Hit(similarity=1 - float(dist), relevant=relevant))
    return hits


def _kept(hits: list[Hit], k: int, threshold: float) -> list[Hit]:
    return [h for h in hits[:k] if h.similarity >= threshold]


def _recall(positives: list[list[Hit]], langs: list[str], k: int, t: float, lang: str | None) -> float:
    picked = [hits for hits, lg in zip(positives, langs) if lang in (None, lg)]
    return sum(any(h.relevant for h in _kept(hits, k, t)) for hits in picked) / len(picked)


def _report(positives: list[list[Hit]], negatives: list[list[Hit]], langs: list[str]) -> None:
    ranked_first = sum(bool(hits) and hits[0].relevant for hits in positives)
    in_top = sum(any(h.relevant for h in hits) for hits in positives)
    print(f"positives={len(positives)} negatives={len(negatives)}")
    print(f"relevant hit ranked first: {ranked_first}/{len(positives)}; "
          f"anywhere in top-{MAX_K}: {in_top}/{len(positives)}")
    print()
    print(" k | thr  | recall all / hu / en | precision | irrelevant/query | negatives with a hit")
    for k in K_VALUES:
        for t in THRESHOLDS:
            kept = [_kept(hits, k, t) for hits in positives]
            rel = sum(h.relevant for hits in kept for h in hits)
            irr = sum(not h.relevant for hits in kept for h in hits)
            fp = sum(bool(_kept(hits, k, t)) for hits in negatives)
            current = k == settings.rag_top_k and abs(t - settings.rag_similarity_threshold) < 1e-9
            print(
                f" {k} | {t:.2f} | {_recall(positives, langs, k, t, None):4.0%} / "
                f"{_recall(positives, langs, k, t, 'hu'):4.0%} / {_recall(positives, langs, k, t, 'en'):4.0%}"
                f"   | {rel / (rel + irr) if rel + irr else 0:5.0%}     | {irr / len(kept):5.2f}"
                f"            | {fp}/{len(negatives)}{'   <-- current' if current else ''}"
            )


async def main() -> None:
    spec = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    async with AsyncSessionLocal() as db:
        positives = [await _top_hits(db, p["query"], p) for p in spec["positives"]]
        negatives = [await _top_hits(db, q, None) for q in spec["negatives"]]
    _report(positives, negatives, [p["lang"] for p in spec["positives"]])


if __name__ == "__main__":
    asyncio.run(main())
