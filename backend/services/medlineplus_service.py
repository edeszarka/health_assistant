"""MedlinePlus Web Service integration with DB caching and rate limiting."""
from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.db_models import MedlinePlusCache


class _TokenBucket:
    """Simple async token-bucket for rate limiting (max 80 req/min)."""

    def __init__(self, rate: int = 80, per: float = 60.0) -> None:
        self._rate = rate          # tokens per period
        self._per = per            # period in seconds
        self._tokens = float(rate)
        self._last_check = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_check
            self._last_check = now
            self._tokens = min(
                self._rate,
                self._tokens + elapsed * (self._rate / self._per),
            )
            if self._tokens < 1:
                wait = (1 - self._tokens) * (self._per / self._rate)
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


_bucket = _TokenBucket()


class MedlinePlusService:
    """Fetches and caches MedlinePlus health topic information."""

    def __init__(self) -> None:
        self._base_url = settings.medlineplus_base_url
        self._connect_url = settings.medlineplus_connect_url
        self._ttl_days = settings.medlineplus_cache_ttl_days

    # ── Public methods ───────────────────────────────────────────────────────

    async def search_health_topic(self, term: str, db: AsyncSession) -> dict:
        """Search MedlinePlus for a health topic by free-text term.

        Checks the DB cache first; fetches from API on cache miss.

        Args:
            term: Free-text search term (e.g. "high blood pressure").
            db: Async DB session.

        Returns:
            Dict with title, summary, url, specialist (or None).
        """
        cache_key = f"topic:{term.lower().strip()}"
        cached = await self._get_cache(cache_key, db)
        if cached:
            return cached

        await _bucket.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self._base_url,
                    params={"db": "healthTopics", "term": term, "rettype": "brief"},
                )
                resp.raise_for_status()
                result = self._parse_topic_xml(resp.text, term)
        except Exception as exc:
            return {
                "title": term,
                "summary": f"Could not retrieve MedlinePlus info: {exc}",
                "url": None,
                "specialist": None,
            }

        await self._set_cache(cache_key, term, result, db)
        return result

    async def get_condition_info(self, icd10_code: str, db: AsyncSession) -> dict:
        """Fetch MedlinePlus Connect info for an ICD-10 code.

        Args:
            icd10_code: ICD-10-CM code (e.g. "E11").
            db: Async DB session.

        Returns:
            Dict with title, summary, url.
        """
        cache_key = f"icd10:{icd10_code.upper().strip()}"
        cached = await self._get_cache(cache_key, db)
        if cached:
            return cached

        await _bucket.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self._connect_url,
                    params={
                        "mainSearchCriteria.v.c": icd10_code,
                        "mainSearchCriteria.v.cs": "2.16.840.1.113883.6.90",
                        "knowledgeResponseType": "application/json",
                    },
                )
                resp.raise_for_status()
                result = self._parse_connect_json(resp.json())
        except Exception as exc:
            return {"title": icd10_code, "summary": str(exc), "url": None}

        await self._set_cache(cache_key, icd10_code, result, db)
        return result

    # ── Parsing helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_topic_xml(xml_text: str, fallback_term: str) -> dict:
        """Parse the wsearch XML response."""
        try:
            root = ET.fromstring(xml_text)
            ns = {"nlm": "https://wsearch.nlm.nih.gov"}
            # Each <document> has <content name="...">
            for doc in root.findall(".//document"):
                title_el = doc.find(".//content[@name='title']")
                summary_el = doc.find(".//content[@name='snippet']")
                url = doc.attrib.get("url", "")
                title = title_el.text.strip() if title_el is not None and title_el.text else fallback_term
                summary = summary_el.text.strip() if summary_el is not None and summary_el.text else ""
                # Remove HTML tags from summary
                summary = ET.tostring(summary_el, encoding="unicode", method="text") if summary_el is not None else summary
                return {"title": title, "summary": summary[:500], "url": url, "specialist": None}
        except Exception:
            pass
        return {"title": fallback_term, "summary": "", "url": None, "specialist": None}

    @staticmethod
    def _parse_connect_json(data: dict) -> dict:
        """Parse MedlinePlus Connect JSON response."""
        try:
            feed = data.get("feed", {})
            entries = feed.get("entry", [{}])
            entry = entries[0] if entries else {}
            title = entry.get("title", {}).get("_value", "")
            summary = entry.get("summary", {}).get("_value", "")[:500]
            links = entry.get("link", [{}])
            url = links[0].get("href", "") if links else ""
            return {"title": title, "summary": summary, "url": url}
        except Exception:
            return {"title": "", "summary": "", "url": None}

    # ── Cache helpers ────────────────────────────────────────────────────────

    async def _get_cache(self, cache_key: str, db: AsyncSession) -> Optional[dict]:
        """Return cached result if not expired, else None."""
        try:
            stmt = select(MedlinePlusCache).where(MedlinePlusCache.cache_key == cache_key)
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row and row.expires_at > datetime.now(timezone.utc):
                return json.loads(row.response_json)
        except Exception:
            pass
        return None

    async def _set_cache(
        self, cache_key: str, term: str, data: dict, db: AsyncSession
    ) -> None:
        """Upsert a cache entry with configured TTL."""
        try:
            expires = datetime.now(timezone.utc) + timedelta(days=self._ttl_days)
            stmt = select(MedlinePlusCache).where(MedlinePlusCache.cache_key == cache_key)
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                row.response_json = json.dumps(data)
                row.expires_at = expires
            else:
                row = MedlinePlusCache(
                    cache_key=cache_key,
                    query_term=term,
                    response_json=json.dumps(data),
                    expires_at=expires,
                )
                db.add(row)
            await db.commit()
        except Exception:
            await db.rollback()


medlineplus_service = MedlinePlusService()
