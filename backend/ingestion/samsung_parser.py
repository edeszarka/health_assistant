"""Samsung Health ZIP export parser."""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, List, Optional, Dict

logger = logging.getLogger(__name__)


@dataclass
class SamsungMetricRaw:
    """A single metric extracted from a Samsung Health export."""

    metric_type: str  # steps / sleep_minutes / heart_rate / weight_kg / bmi / distance_m / etc.
    value: float
    recorded_at: datetime
    source_file: str


@dataclass
class SamsungHealthReport:
    """Consolidated report from Samsung Health parsing."""

    metrics: List[SamsungMetricRaw] = field(default_factory=list)

    def daily_summaries(self) -> List[Dict[str, Any]]:
        """Group metrics by date and return a list of daily summaries."""
        by_date: Dict[date, Dict[str, Any]] = {}
        for m in self.metrics:
            d = m.recorded_at.date()
            if d not in by_date:
                by_date[d] = {
                    "date": d, 
                    "steps": None, 
                    "distance_m": None, 
                    "active_time_min": None, 
                    "active_calories": None,
                    "water_ml": None, 
                    "weight_kg": None, 
                    "bmi": None,
                    "heart_rate": None,
                    "sleep_minutes": None
                }
            
            # Use the latest value for the day for most metrics, 
            # or sum them if it makes sense (not doing sum for now to keep it simple)
            if m.metric_type in by_date[d]:
                by_date[d][m.metric_type] = m.value
        
        return sorted(by_date.values(), key=lambda x: x["date"])

    def summary(self) -> str:
        """Return a human-readable summary of the parsed data."""
        if not self.metrics:
            return "No Samsung Health metrics found."
        
        start = min(m.recorded_at for m in self.metrics)
        end = max(m.recorded_at for m in self.metrics)
        return (f"Samsung Health Report: {len(self.metrics)} metrics "
                f"from {start.date()} to {end.date()}.")


class SamsungHealthParser:
    """Parses Samsung Health ZIP export archives into structured metrics."""

    def parse(self, zip_path: str) -> SamsungHealthReport:
        """Parse a Samsung Health ZIP and return a report."""
        metrics = self.parse_zip(zip_path)
        return SamsungHealthReport(metrics=metrics)

    def parse_zip_bytes(self, zip_bytes: bytes) -> List[SamsungMetricRaw]:
        """Parse Samsung Health ZIP bytes and return metrics."""
        return self.parse_zip(io.BytesIO(zip_bytes))

    def parse_zip(self, zip_input: str | io.BytesIO) -> List[SamsungMetricRaw]:
        """Open a Samsung Health ZIP (path or bytes) and extract metrics."""
        results: List[SamsungMetricRaw] = []
        try:
            with zipfile.ZipFile(zip_input, "r") as zf:
                filenames = zf.namelist()
                for name in filenames:
                    basename = name.split("/")[-1].lower()
                    if not basename.endswith(".csv") and not basename.endswith(".json"):
                        continue
                    
                    if "step_daily_trend" in basename:
                        with zf.open(name) as f:
                            results.extend(self._parse_steps(f.read(), name))
                    elif "sleep" in basename:
                        with zf.open(name) as f:
                            results.extend(self._parse_sleep(f.read(), name))
                    elif "heart_rate" in basename:
                        with zf.open(name) as f:
                            results.extend(self._parse_heart_rate(f.read(), name))
                    elif "body" in basename or "weight" in basename:
                        with zf.open(name) as f:
                            results.extend(self._parse_body(f.read(), name))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse Samsung Health ZIP: {exc}") from exc
        return results

    # ── Private parsers ──────────────────────────────────────────────────────

    def _parse_steps(self, content: bytes, source: str) -> List[SamsungMetricRaw]:
        metrics: List[SamsungMetricRaw] = []
        try:
            rows = self._read_csv(content)
            for row in rows:
                # Handle both epoch and string dates
                ts = self._parse_date(self._get_val(row, ["day_time", "start_time"]))
                count = self._get_val(row, ["count", "step_count"])
                dist = self._get_val(row, ["distance"])
                cal = self._get_val(row, ["calorie", "calories"])

                if ts:
                    if count is not None:
                        metrics.append(SamsungMetricRaw("steps", float(count), ts, source))
                    if dist is not None:
                        metrics.append(SamsungMetricRaw("distance_m", float(dist), ts, source))
                    if cal is not None:
                        metrics.append(SamsungMetricRaw("active_calories", float(cal), ts, source))
        except Exception:
            pass
        return metrics

    def _parse_sleep(self, content: bytes, source: str) -> List[SamsungMetricRaw]:
        metrics: List[SamsungMetricRaw] = []
        try:
            rows = self._read_csv(content)
            for row in rows:
                ts = self._parse_date(self._get_val(row, ["start_time", "day_time"]))
                dur = self._get_val(row, ["sleep_duration", "duration"])
                if ts and dur is not None:
                    minutes = self._duration_to_minutes(str(dur))
                    metrics.append(SamsungMetricRaw("sleep_minutes", minutes, ts, source))
        except Exception:
            pass
        return metrics

    def _parse_heart_rate(self, content: bytes, source: str) -> List[SamsungMetricRaw]:
        metrics: List[SamsungMetricRaw] = []
        try:
            rows = self._read_csv(content)
            for row in rows:
                ts = self._parse_date(self._get_val(row, ["start_time", "day_time"]))
                val = self._get_val(row, ["heart_rate", "bpm", "avg"])
                if ts and val is not None:
                    metrics.append(SamsungMetricRaw("heart_rate", float(val), ts, source))
        except Exception:
            pass
        return metrics

    def _parse_body(self, content: bytes, source: str) -> List[SamsungMetricRaw]:
        metrics: List[SamsungMetricRaw] = []
        try:
            rows = self._read_csv(content)
            for row in rows:
                ts = self._parse_date(self._get_val(row, ["start_time", "day_time"]))
                weight = self._get_val(row, ["weight", "weight_kg"])
                bmi = self._get_val(row, ["bmi"])
                if ts:
                    if weight is not None:
                        metrics.append(SamsungMetricRaw("weight_kg", float(weight), ts, source))
                    if bmi is not None:
                        metrics.append(SamsungMetricRaw("bmi", float(bmi), ts, source))
        except Exception:
            pass
        return metrics

    # ── Utilities ────────────────────────────────────────────────────────────

    def _get_val(self, row: Dict[str, Any], candidates: List[str]) -> Any:
        """Get value from row checking for prefixed column names."""
        for c in candidates:
            # Direct match
            if c in row: return row[c]
            # Prefix match (Samsung often uses 'com.samsung.health.steps.count')
            for k in row.keys():
                if k.endswith("." + c) or k.endswith("_" + c):
                    return row[k]
        return None

    @staticmethod
    def _read_csv(content: bytes) -> List[Dict[str, Any]]:
        """Robust CSV reader that skips metadata headers."""
        for encoding in ("utf-8", "utf-16", "utf-8-sig", "latin-1"):
            try:
                text = content.decode(encoding)
                if encoding == "utf-16" and "\x00" in text[:100]: continue
                
                lines = text.splitlines()
                # Find the header row (skipping Samsung's metadata rows like "com.samsung.health...,123")
                header_idx = 0
                for i, line in enumerate(lines):
                    if "," in line and any(kw in line.lower() for kw in ["time", "date", "count", "value", "weight"]):
                        header_idx = i
                        break
                
                reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
                rows = list(reader)
                if rows: return rows
            except Exception:
                continue
        return []

    @staticmethod
    def _parse_date(raw: Any) -> Optional[datetime]:
        if not raw: return None
        raw_str = str(raw).strip()
        
        # Support epoch milliseconds
        if raw_str.isdigit() and len(raw_str) >= 10:
            try:
                return datetime.fromtimestamp(int(raw_str) / 1000.0)
            except Exception:
                pass

        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
        ):
            try:
                return datetime.strptime(raw_str, fmt)
            except ValueError:
                continue

        if len(raw_str) > 19:
            try:
                return datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
            except ValueError:
                pass
        return None

    @staticmethod
    def _duration_to_minutes(raw: str) -> float:
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
