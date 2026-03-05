"""Samsung Health ZIP export parser."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class SamsungMetricRaw:
    """A single metric extracted from a Samsung Health export."""

    metric_type: str   # steps / sleep_minutes / heart_rate / weight_kg / bmi
    value: float
    recorded_at: datetime
    source_file: str


class SamsungHealthParser:
    """Parses Samsung Health ZIP export archives into structured metrics."""

    def parse_zip(self, zip_path: str) -> list[SamsungMetricRaw]:
        """Open a Samsung Health ZIP and extract all recognised metrics.

        Args:
            zip_path: Absolute path to the ZIP file.

        Returns:
            List of SamsungMetricRaw objects.
        """
        results: list[SamsungMetricRaw] = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in zf.namelist():
                    lower = name.lower()
                    with zf.open(name) as f:
                        content = f.read()
                    if "step_daily_trend" in lower:
                        results.extend(self._parse_steps(content, name))
                    elif "sleep" in lower:
                        results.extend(self._parse_sleep(content, name))
                    elif "heart_rate" in lower:
                        results.extend(self._parse_heart_rate(content, name))
                    elif "body" in lower:
                        results.extend(self._parse_body(content, name))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse Samsung Health ZIP: {exc}") from exc
        return results

    def parse_zip_bytes(self, content: bytes, filename: str = "samsung.zip") -> list[SamsungMetricRaw]:
        """Parse directly from in-memory ZIP bytes.

        Args:
            content: Raw bytes of the ZIP file.
            filename: Original filename (used on metrics for traceability).

        Returns:
            List of SamsungMetricRaw objects.
        """
        results: list[SamsungMetricRaw] = []
        try:
            with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
                for name in zf.namelist():
                    lower = name.lower()
                    with zf.open(name) as f:
                        file_content = f.read()
                    if "step_daily_trend" in lower:
                        results.extend(self._parse_steps(file_content, name))
                    elif "sleep" in lower:
                        results.extend(self._parse_sleep(file_content, name))
                    elif "heart_rate" in lower:
                        results.extend(self._parse_heart_rate(file_content, name))
                    elif "body" in lower:
                        results.extend(self._parse_body(file_content, name))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse Samsung Health ZIP bytes: {exc}") from exc
        return results

    # ── Private parsers ──────────────────────────────────────────────────────

    def _parse_steps(self, content: bytes, source: str) -> list[SamsungMetricRaw]:
        """Parse step count CSV/JSON."""
        metrics: list[SamsungMetricRaw] = []
        try:
            rows = self._read_csv(content)
            for row in rows:
                # Samsung format typically has 'day_time' and 'count' columns
                ts = self._parse_date(row.get("day_time") or row.get("start_time") or "")
                val = float(row.get("count") or row.get("step_count") or 0)
                if ts and val:
                    metrics.append(SamsungMetricRaw("steps", val, ts, source))
        except Exception:
            pass
        return metrics

    def _parse_sleep(self, content: bytes, source: str) -> list[SamsungMetricRaw]:
        """Parse sleep duration CSV/JSON into total minutes."""
        metrics: list[SamsungMetricRaw] = []
        try:
            rows = self._read_csv(content)
            for row in rows:
                ts = self._parse_date(row.get("start_time") or row.get("day_time") or "")
                # duration may be in minutes already or in HH:MM format
                raw_dur = str(row.get("sleep_duration") or row.get("duration") or "0")
                minutes = self._duration_to_minutes(raw_dur)
                if ts and minutes:
                    metrics.append(SamsungMetricRaw("sleep_minutes", minutes, ts, source))
        except Exception:
            pass
        return metrics

    def _parse_heart_rate(self, content: bytes, source: str) -> list[SamsungMetricRaw]:
        """Parse heart rate CSV/JSON (average per entry)."""
        metrics: list[SamsungMetricRaw] = []
        try:
            rows = self._read_csv(content)
            for row in rows:
                ts = self._parse_date(row.get("start_time") or row.get("day_time") or "")
                val = float(row.get("heart_rate") or row.get("bpm") or row.get("avg") or 0)
                if ts and val:
                    metrics.append(SamsungMetricRaw("heart_rate", val, ts, source))
        except Exception:
            pass
        return metrics

    def _parse_body(self, content: bytes, source: str) -> list[SamsungMetricRaw]:
        """Parse body composition CSV/JSON into weight_kg and bmi."""
        metrics: list[SamsungMetricRaw] = []
        try:
            rows = self._read_csv(content)
            for row in rows:
                ts = self._parse_date(row.get("start_time") or row.get("day_time") or "")
                weight = row.get("weight") or row.get("weight_kg")
                bmi = row.get("bmi")
                if ts and weight:
                    metrics.append(SamsungMetricRaw("weight_kg", float(weight), ts, source))
                if ts and bmi:
                    metrics.append(SamsungMetricRaw("bmi", float(bmi), ts, source))
        except Exception:
            pass
        return metrics

    # ── Utilities ────────────────────────────────────────────────────────────

    @staticmethod
    def _read_csv(content: bytes) -> list[dict[str, Any]]:
        """Try CSV; fall back to JSON."""
        try:
            text = content.decode("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            return list(reader)
        except Exception:
            pass
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    @staticmethod
    def _parse_date(raw: str) -> datetime | None:
        """Try several date formats used by Samsung Health."""
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.strip(), fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _duration_to_minutes(raw: str) -> float:
        """Convert a duration string (HH:MM or plain number) to float minutes."""
        raw = raw.strip()
        if ":" in raw:
            parts = raw.split(":")
            try:
                return int(parts[0]) * 60 + int(parts[1])
            except ValueError:
                return 0.0
        try:
            return float(raw)
        except ValueError:
            return 0.0
