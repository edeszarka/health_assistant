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
import logging

logger = logging.getLogger(__name__)


class _TokenBucket:
    """Simple async token-bucket for rate limiting.
    
    Ensures we don't exceed the MedlinePlus API usage guidelines 
    (default: max 80 requests per minute).
    """

    def __init__(self, rate: int = 80, per: float = 60.0) -> None:
        """Initializes the bucket.
        
        Args:
            rate: Maximum number of tokens allowed per period.
            per: The period duration in seconds.
        """
        self._rate = rate  # tokens per period
        self._per = per  # period in seconds
        self._tokens = float(rate)
        # Handle cases where there might not be a running loop during init
        try:
            self._last_check = asyncio.get_event_loop().time()
        except RuntimeError:
            self._last_check = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available in the bucket."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            if self._last_check == 0.0:
                self._last_check = now

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
    """Fetches and caches MedlinePlus health topic information from NIH APIs."""

    def __init__(self) -> None:
        """Initializes the service with settings from config."""
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
            logger.error(f"MedlinePlus search failed for '{term}': {exc}")
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
            logger.error(f"MedlinePlus Connect failed for '{icd10_code}': {exc}")
            return {"title": icd10_code, "summary": str(exc), "url": None}

        await self._set_cache(cache_key, icd10_code, result, db)
        return result

    # ── Parsing helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_topic_xml(xml_text: str, fallback_term: str) -> dict:
        """Parse the wsearch XML response into a structured dict.
        
        Args:
            xml_text: The raw XML response body.
            fallback_term: Title to use if parsing fails.
            
        Returns:
            Dictionary containing title, summary, and url.
        """
        try:
            root = ET.fromstring(xml_text)
            # Each <document> has <content name="...">
            for doc in root.findall(".//document"):
                title_el = doc.find(".//content[@name='title']")
                summary_el = doc.find(".//content[@name='snippet']")
                url = doc.attrib.get("url", "")
                title = (
                    title_el.text.strip()
                    if title_el is not None and title_el.text
                    else fallback_term
                )
                # Remove HTML tags from summary
                summary = (
                    ET.tostring(summary_el, encoding="unicode", method="text")
                    if summary_el is not None
                    else ""
                )
                return {
                    "title": title,
                    "summary": summary[:500].strip(),
                    "url": url,
                    "specialist": None,
                }
        except Exception as exc:
            logger.warning(f"Failed to parse MedlinePlus XML: {exc}")
        
        return {"title": fallback_term, "summary": "", "url": None, "specialist": None}

    @staticmethod
    def _parse_connect_json(data: dict) -> dict:
        """Parse MedlinePlus Connect JSON response.
        
        Args:
            data: Decoded JSON response.
            
        Returns:
            Dictionary containing title, summary, and url.
        """
        try:
            feed = data.get("feed", {})
            entries = feed.get("entry", [{}])
            entry = entries[0] if entries else {}
            title = entry.get("title", {}).get("_value", "")
            summary = entry.get("summary", {}).get("_value", "")[:500]
            links = entry.get("link", [{}])
            url = links[0].get("href", "") if links else ""
            return {"title": title, "summary": summary, "url": url}
        except Exception as exc:
            logger.warning(f"Failed to parse MedlinePlus Connect JSON: {exc}")
            return {"title": "", "summary": "", "url": None}

    # ── Cache helpers ────────────────────────────────────────────────────────

    async def _get_cache(self, cache_key: str, db: AsyncSession) -> Optional[dict]:
        """Return cached result if not expired, else None.
        
        Args:
            cache_key: Unique identifier for the search.
            db: Async DB session.
        """
        try:
            stmt = select(MedlinePlusCache).where(
                MedlinePlusCache.cache_key == cache_key
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row and row.expires_at > datetime.now(timezone.utc):
                return json.loads(row.response_json)
        except Exception as exc:
            logger.warning(f"MedlinePlus cache read failed: {exc}")
        return None

    async def _set_cache(
        self, cache_key: str, term: str, data: dict, db: AsyncSession
    ) -> None:
        """Upsert a cache entry with configured TTL.
        
        Args:
            cache_key: Unique identifier for the search.
            term: The original search term.
            data: The parsed data to store.
            db: Async DB session.
        """
        try:
            expires = datetime.now(timezone.utc) + timedelta(days=self._ttl_days)
            stmt = select(MedlinePlusCache).where(
                MedlinePlusCache.cache_key == cache_key
            )
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
        except Exception as exc:
            logger.warning(f"MedlinePlus cache write failed: {exc}")
            await db.rollback()


medlineplus_service = MedlinePlusService()
