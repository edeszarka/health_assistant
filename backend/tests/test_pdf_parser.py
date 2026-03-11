"""Tests for PDFParser."""
from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, patch

import pytest

from ingestion.pdf_parser import PDFParser


def test_pdf_parser_is_callable():
    """PDFParser should be importable and instantiable."""
    parser = PDFParser()
    assert callable(parser.extract_text)
    assert callable(parser.parse_lab_results)


@patch("pdfplumber.open")
def test_extract_text_returns_combined_pages(mock_open):
    """extract_text should concatenate page text from all pages."""
    mock_page1 = type("Page", (), {"extract_text": lambda self: "Page one content"})()
    mock_page2 = type("Page", (), {"extract_text": lambda self: "Page two content"})()
    mock_pdf = type("PDF", (), {
        "__enter__": lambda self, *a: self,
        "__exit__": lambda self, *a: None,
        "pages": [mock_page1, mock_page2],
    })()
    mock_open.return_value = mock_pdf

    parser = PDFParser()
    result = parser.extract_text("/fake/path.pdf")
    assert "Page one content" in result
    assert "Page two content" in result


@pytest.mark.asyncio
async def test_extract_from_text_strips_markdown_fences():
    """parse_lab_results_from_bytes should strip ```json fences from LLM response."""
    fake_llm_response = '```json\n[{"raw_name": "Hemoglobin", "value": 14.0, "unit": "g/dL", "ref_range_low": 12.0, "ref_range_high": 17.0, "test_date": null}]\n```'

    parser = PDFParser()

    with patch.object(parser, "extract_text_from_bytes", return_value="some extracted text"):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = AsyncMock()
            mock_resp.json.return_value = {"response": fake_llm_response}
            mock_resp.raise_for_status = AsyncMock()
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await parser.parse_lab_results_from_bytes(b"fake pdf bytes")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["raw_name"] == "Hemoglobin"
    assert result[0]["value"] == 14.0
