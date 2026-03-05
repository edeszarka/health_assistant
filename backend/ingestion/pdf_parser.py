"""PDF parsing and lab result extraction using pdfplumber + Ollama LLM."""
from __future__ import annotations

import json
import re
import io
from typing import Any

import httpx
import pdfplumber

from backend.config import settings


class PDFParser:
    """Parses medical PDF reports and extracts structured lab data via LLM."""

    def __init__(self) -> None:
        self._ollama_url = f"{settings.ollama_base_url}/api/generate"
        self._model = settings.ollama_model

    # ── Public helpers ───────────────────────────────────────────────────────

    def extract_text(self, file_path: str) -> str:
        """Extract all text from a PDF file.

        Args:
            file_path: Absolute path to the PDF.

        Returns:
            Concatenated text from all pages.
        """
        try:
            with pdfplumber.open(file_path) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(pages)
        except Exception as exc:
            raise RuntimeError(f"Failed to read PDF '{file_path}': {exc}") from exc

    def extract_text_from_bytes(self, content: bytes) -> str:
        """Extract text directly from raw PDF bytes.

        Args:
            content: Raw bytes of the PDF file.

        Returns:
            Concatenated text from all pages.
        """
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(pages)
        except Exception as exc:
            raise RuntimeError(f"Failed to parse PDF bytes: {exc}") from exc

    def extract_tables(self, file_path: str) -> list[dict[str, Any]]:
        """Extract all tables found in a PDF.

        Args:
            file_path: Absolute path to the PDF.

        Returns:
            List of dicts representing rows from all tables.
        """
        results: list[dict[str, Any]] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    for table in page.extract_tables():
                        if not table:
                            continue
                        headers = [str(h).strip() if h else "" for h in table[0]]
                        for row in table[1:]:
                            results.append(
                                dict(zip(headers, [str(c).strip() if c else "" for c in row]))
                            )
        except Exception as exc:
            raise RuntimeError(f"Failed to extract tables from '{file_path}': {exc}") from exc
        return results

    async def parse_lab_results(self, file_path: str) -> list[dict[str, Any]]:
        """Use Ollama LLM to extract structured lab values from a PDF.

        Args:
            file_path: Absolute path to the PDF.

        Returns:
            List of dicts with keys: raw_name, value, unit,
            ref_range_low, ref_range_high, test_date.
        """
        text = self.extract_text(file_path)
        return await self._extract_from_text(text)

    async def parse_lab_results_from_bytes(self, content: bytes, filename: str = "") -> list[dict[str, Any]]:
        """Use Ollama LLM to extract structured lab values from raw PDF bytes.

        Args:
            content: Raw bytes of the PDF file.
            filename: Original filename (for error messages).

        Returns:
            List of dicts with keys: raw_name, value, unit,
            ref_range_low, ref_range_high, test_date.
        """
        text = self.extract_text_from_bytes(content)
        return await self._extract_from_text(text)

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _extract_from_text(self, text: str) -> list[dict[str, Any]]:
        """Send text to Ollama and parse the JSON response."""
        prompt = (
            "You are a medical data extraction assistant. "
            "Extract all lab test results from the following text.\n"
            "The text may be in Hungarian, Latin medical terminology, or English — handle all three.\n"
            "Return ONLY a valid JSON array. Each item must have exactly these keys:\n"
            '- "raw_name": the test name exactly as it appears in the text\n'
            '- "value": numeric value as a float\n'
            '- "unit": unit of measurement as a string\n'
            '- "ref_range_low": lower bound of reference range as float or null\n'
            '- "ref_range_high": upper bound of reference range as float or null\n'
            '- "test_date": date in ISO format YYYY-MM-DD or null if not found\n\n'
            f"Text to parse:\n{text}\n\n"
            "Return ONLY the JSON array, no explanation, no markdown."
        )

        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(self._ollama_url, json=payload)
                resp.raise_for_status()
                raw = resp.json().get("response", "")
        except Exception as exc:
            raise RuntimeError(f"Ollama call failed during lab extraction: {exc}") from exc

        # Strip markdown fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip()
        raw = raw.rstrip("`").strip()

        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return data
        except json.JSONDecodeError:
            # Try to find a JSON array in the text
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            return []
