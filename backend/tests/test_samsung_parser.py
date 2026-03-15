"""Tests for SamsungHealthParser."""
from __future__ import annotations

import csv
import io
import zipfile

import pytest

from ingestion.samsung_parser import SamsungHealthParser


def _make_zip(filenames_and_contents: dict[str, bytes]) -> bytes:
    """Helper: build an in-memory ZIP from a dict of {filename: bytes}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in filenames_and_contents.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf.read()


def _csv_bytes(rows: list[dict]) -> bytes:
    """Helper: serialise a list of dicts to CSV bytes."""
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def test_parse_steps():
    """Should extract step count metrics from step_daily_trend CSV."""
    csv_data = _csv_bytes([
        {"day_time": "2024-01-15 00:00:00", "count": "8500"},
        {"day_time": "2024-01-16 00:00:00", "count": "10200"},
    ])
    zip_bytes = _make_zip({"step_daily_trend_20240116.csv": csv_data})

    parser = SamsungHealthParser()
    metrics = parser.parse_zip_bytes(zip_bytes)

    step_metrics = [m for m in metrics if m.metric_type == "steps"]
    assert len(step_metrics) == 2
    assert step_metrics[0].value == 8500.0


def test_parse_heart_rate():
    """Should extract heart rate metrics from heart_rate CSV."""
    csv_data = _csv_bytes([
        {"start_time": "2024-01-15 08:00:00", "heart_rate": "68"},
    ])
    zip_bytes = _make_zip({"heart_rate_20240115.csv": csv_data})

    parser = SamsungHealthParser()
    metrics = parser.parse_zip_bytes(zip_bytes)

    hr_metrics = [m for m in metrics if m.metric_type == "heart_rate"]
    assert len(hr_metrics) == 1
    assert hr_metrics[0].value == 68.0


def test_parse_body_weight_and_bmi():
    """Should extract weight_kg and bmi from body CSV."""
    csv_data = _csv_bytes([
        {"start_time": "2024-01-15 09:00:00", "weight": "82.5", "bmi": "25.3"},
    ])
    zip_bytes = _make_zip({"body_20240115.csv": csv_data})

    parser = SamsungHealthParser()
    metrics = parser.parse_zip_bytes(zip_bytes)

    weight = [m for m in metrics if m.metric_type == "weight_kg"]
    bmi = [m for m in metrics if m.metric_type == "bmi"]
    assert len(weight) == 1
    assert weight[0].value == 82.5
    assert len(bmi) == 1
    assert bmi[0].value == 25.3


def test_empty_zip():
    """An empty ZIP should return an empty list, not raise."""
    zip_bytes = _make_zip({})
    parser = SamsungHealthParser()
    result = parser.parse_zip_bytes(zip_bytes)
    assert result == []
