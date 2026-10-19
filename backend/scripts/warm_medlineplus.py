"""Prefetch MedlinePlus Connect lab-test texts for the fixed LOINC list.

The chat reads MedlinePlus texts from the cache only. This script fills that
cache for every code in ``services.lab_loinc.LAB_LOINC``, whatever the user's
results are, so the requests sent to NLM are the same for everyone and reveal
nothing about the user. Run inside the backend container; a dry run is the
default:

    python -m scripts.warm_medlineplus          # cache state only, no requests
    python -m scripts.warm_medlineplus --apply  # fetch missing and expired codes

Requests go through the service's rate limiter (NLM allows 100 per minute per
IP). Prints lab keys, codes and found/empty only.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import AsyncSessionLocal
from services.lab_loinc import LAB_LOINC
from services.medlineplus_service import (
    LOINC_SYSTEM,
    connect_cache_key,
    medlineplus_service,
)


@dataclass
class Outcome:
    keys: list[str]
    code: str
    state: str  # ok / expired / missing (before)
    result: str = "-"  # found / empty / failed / - (not fetched)


def unique_codes() -> dict[str, list[str]]:
    """Map each LOINC code to the lab keys that use it."""
    codes: dict[str, list[str]] = {}
    for key, code in LAB_LOINC.items():
        codes.setdefault(code, []).append(key)
    return codes


async def _state(db: AsyncSession, code: str) -> str:
    """Return the cache state of one code: ok, expired or missing."""
    key = connect_cache_key(code, LOINC_SYSTEM)
    if await medlineplus_service.get_cached(key, db, allow_expired=False):
        return "ok"
    if await medlineplus_service.get_cached(key, db, allow_expired=True):
        return "expired"
    return "missing"


def classify(result: dict) -> str:
    """Describe a fetch result: found, empty (no MedlinePlus page) or failed."""
    if result.get("url") is None:
        return "failed"
    return "found" if result.get("summary") else "empty"


async def warm(db: AsyncSession, apply: bool) -> list[Outcome]:
    """Report (and with ``apply`` refresh) the cache state of every code."""
    outcomes = []
    for code, keys in unique_codes().items():
        outcome = Outcome(keys=keys, code=code, state=await _state(db, code))
        if apply and outcome.state != "ok":
            result = await medlineplus_service.get_connect_info(
                code, LOINC_SYSTEM, db, refresh=True
            )
            outcome.result = classify(result)
        outcomes.append(outcome)
    return outcomes


def _print(outcomes: list[Outcome], apply: bool) -> None:
    print("lab key(s) | LOINC | cache before | result")
    for o in outcomes:
        print(f"{', '.join(o.keys):28} | {o.code:8} | {o.state:12} | {o.result}")
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.result if apply else o.state] = counts.get(o.result if apply else o.state, 0) + 1
    summary = " ".join(f"{name}={n}" for name, n in sorted(counts.items()))
    print(f"codes={len(outcomes)} {summary}"
          + ("" if apply else " (dry run: no requests sent)"))


async def main(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        outcomes = await warm(db, apply)
    _print(outcomes, apply)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument("--apply", action="store_true", help="fetch missing and expired codes")
    asyncio.run(main(cli.parse_args().apply))
