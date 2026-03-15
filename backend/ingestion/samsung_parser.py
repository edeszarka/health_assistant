"""
SamsungHealthParser — Samsung Health GDPR export parser.
Designed for Samsung S23 (no Galaxy Watch) + Mi Band 5 setup.

Export instructions:
    Samsung Health app → Profile (bottom right) → Settings (gear icon)
    → Download personal data → request → unzip received file

Export format:
    ZIP containing CSV files named:
        com.samsung.shealth.<type>.<timestamp>.csv
    Each CSV has TWO header rows:
        Row 1: metadata / package name (skip)
        Row 2: actual column names (prefixed with package path)
    Timestamps: UTC, with a separate *time_offset column (+02:00 etc.)

Data available on S23 without Galaxy Watch:
    ✅ step_daily_trend      — daily steps, distance, calories (PRIMARY)
    ✅ pedometer_day_summary — daily step totals from phone pedometer
    ✅ exercise              — manually started workouts (GPS, duration)
    ✅ activity.day_summary  — daily active time, calories
    ✅ weight                — manual entries
    ✅ water_intake          — manual entries
    ✅ food_intake           — manual entries (if used)
    ❌ heart_rate            — NOT available without Galaxy Watch
    ❌ sleep_stage           — NOT available without Galaxy Watch
    ❌ blood_pressure        — NOT available without Galaxy Watch

Gap awareness:
    Steps ARE recorded during the Feb 2024 – Feb 2026 Mi Band gap
    (the phone pedometer always runs). The parser treats step data
    as continuous and does NOT exclude the gap period from step
    calculations. Gap annotations are added only to metrics that
    require the Mi Band (HR, sleep, SpO2).

Multiple-source merging:
    Samsung Health stores one row per source device per day.
    The parser sums steps across sources for the same day
    (phone + any synced wearable) to get the true daily total.

Usage:
    parser = SamsungHealthParser()
    report = parser.parse("path/to/samsunghealth_export.zip")

    print(report.summary())
    daily = report.daily_summaries()   # list of dicts, one per day
    data  = report.to_dict()           # full serialization
"""

import csv
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Known Mi Band gap — steps still tracked by phone during this period
MI_BAND_GAP_START = date(2024, 2, 1)
MI_BAND_GAP_END   = date(2026, 2, 1)

# Samsung Health exercise type codes → human-readable names
EXERCISE_TYPE_MAP = {
    "1001": "walking",
    "1002": "running",
    "2001": "cycling",
    "3001": "hiking",
    "4001": "swimming",
    "5001": "gym_workout",
    "6001": "yoga",
    "7001": "elliptical",
    "8001": "rowing",
    "10001": "other",
    "11007": "pilates",
    "13001": "basketball",
    "13002": "football",
    "13003": "baseball",
    "13004": "tennis",
    "13007": "badminton",
    "15001": "dancing",
    "16001": "jump_rope",
}

# Files we actually care about for S23 setup
TARGET_FILES = {
    "step_daily_trend":      "steps",
    "pedometer_day_summary": "steps_fallback",
    "exercise":              "exercise",
    "activity.day_summary":  "activity",
    "weight":                "weight",
    "water_intake":          "water",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DailySteps:
    date:             date
    steps:            int
    distance_meters:  float
    calories:         float
    active_time_min:  int
    source:           str    # "phone", "wearable", "merged"


@dataclass
class ExerciseSession:
    date:             date
    start:            datetime
    end:              Optional[datetime]
    exercise_type:    str
    duration_minutes: int
    distance_meters:  float
    calories:         float
    mean_heart_rate:  Optional[int]   # only if Galaxy Watch present
    max_heart_rate:   Optional[int]
    steps:            Optional[int]
    notes:            Optional[str]


@dataclass
class ActivityDay:
    date:            date
    active_calories: float
    total_calories:  float
    active_minutes:  int


@dataclass
class WeightEntry:
    date:       date
    weight_kg:  float
    bmi:        Optional[float]
    body_fat:   Optional[float]


@dataclass
class WaterIntakeDay:
    date:     date
    ml:       float


@dataclass
class DataNote:
    """Annotation about a data quirk or gap."""
    date_range_start: date
    date_range_end:   date
    note_type:        str    # "mi_band_gap", "data_gap", "merged_sources"
    message:          str


@dataclass
class SamsungReport:
    """Full parsed result from a Samsung Health export."""
    steps:      list[DailySteps]     = field(default_factory=list)
    exercise:   list[ExerciseSession]= field(default_factory=list)
    activity:   list[ActivityDay]    = field(default_factory=list)
    weight:     list[WeightEntry]    = field(default_factory=list)
    water:      list[WaterIntakeDay] = field(default_factory=list)
    notes:      list[DataNote]       = field(default_factory=list)
    parse_errors: list[str]          = field(default_factory=list)
    files_found:  list[str]          = field(default_factory=list)

    # ---- Aggregate accessors ----------------------------------------

    def date_range(self) -> tuple[Optional[date], Optional[date]]:
        all_dates = [s.date for s in self.steps]
        if not all_dates:
            return None, None
        return min(all_dates), max(all_dates)

    def avg_steps(self, days: int = 30) -> Optional[float]:
        """Average daily steps over recent N days. Includes gap period."""
        cutoff = date.today() - timedelta(days=days)
        recent = [s.steps for s in self.steps if s.date >= cutoff]
        return round(mean(recent), 0) if recent else None

    def avg_steps_in_gap(self) -> Optional[float]:
        """
        Average steps specifically during the Mi Band gap period.
        Useful for FINDRISC physical activity estimation when HR unavailable.
        """
        gap_steps = [
            s.steps for s in self.steps
            if MI_BAND_GAP_START <= s.date <= MI_BAND_GAP_END
        ]
        return round(mean(gap_steps), 0) if gap_steps else None

    def step_coverage_pct(self) -> float:
        """
        What % of days in the total date range have step data.
        Low % indicates sync gaps or app not running.
        """
        start, end = self.date_range()
        if not start or not end:
            return 0.0
        total_days = (end - start).days + 1
        recorded_days = len(set(s.date for s in self.steps))
        return round(recorded_days / total_days * 100, 1)

    def latest_weight(self) -> Optional[WeightEntry]:
        if not self.weight:
            return None
        return sorted(self.weight, key=lambda w: w.date)[-1]

    def gap_step_vs_normal_comparison(self) -> Optional[dict]:
        """
        Compare step counts inside vs outside the Mi Band gap.
        Useful context for FINDRISC: was physical activity maintained?
        """
        pre_gap  = [s.steps for s in self.steps if s.date < MI_BAND_GAP_START]
        in_gap   = [s.steps for s in self.steps
                    if MI_BAND_GAP_START <= s.date <= MI_BAND_GAP_END]
        post_gap = [s.steps for s in self.steps if s.date > MI_BAND_GAP_END]

        result = {}
        if pre_gap:
            result["pre_gap_avg"]  = round(mean(pre_gap), 0)
        if in_gap:
            result["in_gap_avg"]   = round(mean(in_gap), 0)
        if post_gap:
            result["post_gap_avg"] = round(mean(post_gap), 0)

        if "pre_gap_avg" in result and "in_gap_avg" in result:
            delta = result["in_gap_avg"] - result["pre_gap_avg"]
            result["gap_delta"] = round(delta, 0)
            result["activity_maintained"] = delta >= -1500   # within 1500 steps = maintained

        return result if result else None

    # ---- Daily summary ----------------------------------------------

    def daily_summaries(self) -> list[dict]:
        """
        One dict per day merging steps + activity + water.
        Used for DB storage and dashboard charts.
        """
        step_by_date     = {s.date: s for s in self.steps}
        activity_by_date = {a.date: a for a in self.activity}
        water_by_date    = {w.date: w for w in self.water}

        all_dates = set(step_by_date) | set(activity_by_date)
        summaries = []

        for d in sorted(all_dates):
            s = step_by_date.get(d)
            a = activity_by_date.get(d)
            w = water_by_date.get(d)
            in_gap = MI_BAND_GAP_START <= d <= MI_BAND_GAP_END

            summaries.append({
                "date":              d.isoformat(),
                "in_mi_band_gap":    in_gap,
                "steps":             s.steps if s else None,
                "distance_m":        s.distance_meters if s else None,
                "step_calories":     s.calories if s else None,
                "active_time_min":   s.active_time_min if s else None,
                "active_calories":   a.active_calories if a else None,
                "total_calories":    a.total_calories if a else None,
                "water_ml":          w.ml if w else None,
                "data_source":       s.source if s else None,
            })
        return summaries

    # ---- Serialization ----------------------------------------------

    def summary(self) -> str:
        start, end = self.date_range()
        gap_data  = self.gap_step_vs_normal_comparison()
        lines = [
            "Samsung Health Export Summary",
            "=" * 50,
            f"Data range    : {start} → {end}",
            f"Step days     : {len(self.steps)} days ({self.step_coverage_pct()}% coverage)",
            f"Exercise sess.: {len(self.exercise)}",
            f"Weight entries: {len(self.weight)}",
            f"Water entries : {len(self.water)}",
            f"Files found   : {', '.join(self.files_found)}",
        ]
        avg = self.avg_steps()
        if avg:
            lines.append(f"Avg steps (30d): {int(avg):,}")

        gap_avg = self.avg_steps_in_gap()
        if gap_avg:
            lines.append(f"Avg steps during Mi Band gap: {int(gap_avg):,}")

        if gap_data:
            lines.append(f"Pre-gap avg steps : {int(gap_data.get('pre_gap_avg', 0)):,}")
            lines.append(f"In-gap avg steps  : {int(gap_data.get('in_gap_avg', 0)):,}")
            if "post_gap_avg" in gap_data:
                lines.append(f"Post-gap avg steps: {int(gap_data.get('post_gap_avg', 0)):,}")
            maintained = gap_data.get("activity_maintained")
            if maintained is not None:
                label = "✅ maintained" if maintained else "⚠️ reduced"
                lines.append(f"Activity during gap: {label}")

        w = self.latest_weight()
        if w:
            lines.append(f"Latest weight : {w.weight_kg} kg (BMI: {w.bmi})")
        if self.parse_errors:
            lines.append(f"Parse errors  : {len(self.parse_errors)}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        start, end = self.date_range()
        return {
            "date_range": {
                "start": start.isoformat() if start else None,
                "end":   end.isoformat() if end else None,
            },
            "mi_band_gap": {
                "start": MI_BAND_GAP_START.isoformat(),
                "end":   MI_BAND_GAP_END.isoformat(),
                "step_data_available": self.avg_steps_in_gap() is not None,
                "gap_comparison": self.gap_step_vs_normal_comparison(),
            },
            "aggregates": {
                "avg_steps_30d":       self.avg_steps(30),
                "avg_steps_in_gap":    self.avg_steps_in_gap(),
                "step_coverage_pct":   self.step_coverage_pct(),
                "total_exercise_sessions": len(self.exercise),
                "latest_weight_kg":    self.latest_weight().weight_kg if self.latest_weight() else None,
                "latest_bmi":          self.latest_weight().bmi if self.latest_weight() else None,
            },
            "daily_summaries": self.daily_summaries(),
            "files_found":  self.files_found,
            "parse_errors": self.parse_errors,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt_samsung(date_str: str, offset_str: str = "") -> Optional[datetime]:
    """
    Parse Samsung Health datetime + UTC offset into local datetime.
    Samsung stores: '2024-01-15 08:23:00.000' with offset '+01:00'
    Or numeric timestamps: '1576368000000' (milliseconds)
    """
    if not date_str:
        return None
        
    date_str = str(date_str).strip()
    offset_str = str(offset_str or "").strip()

    if not date_str:
        return None

    # Handle numeric timestamps (milliseconds)
    if date_str.isdigit() and len(date_str) >= 10:
        try:
            ts = float(date_str) / 1000.0
            return datetime.fromtimestamp(ts)
        except Exception:
            pass

    # Strip milliseconds from ISO-like strings
    date_str = re.sub(r"\.\d+$", "", date_str)

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    dt = None
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue

    if dt is None:
        return None

    # Apply UTC offset to get local time
    if offset_str and offset_str not in ("", "UTC"):
        try:
            sign = 1 if "+" in offset_str else -1
            parts = offset_str.replace("+", "").replace("-", "").split(":")
            hours = int(parts[0])
            mins  = int(parts[1]) if len(parts) > 1 else 0
            delta = timedelta(hours=hours, minutes=mins)
            dt    = dt + sign * delta
        except Exception:
            pass  # keep UTC time if offset parsing fails

    return dt


def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return default


def _safe_int(val: str, default: int = 0) -> int:
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


def _strip_prefix(col: str) -> str:
    """
    Remove Samsung Health package prefix from column name.
    'com.samsung.shealth.step_daily_trend.step_count' → 'step_count'
    'com.samsung.health.weight.weight' → 'weight'
    """
    if col is None:
        return ""
    return str(col).strip().split(".")[-1]


def _find_col(
    row: dict,
    candidates: list[str],
    strip_prefix: bool = True,
) -> Optional[str]:
    """
    Find the first matching column key in a CSV row dict.
    Tries both full package name and stripped suffix.
    """
    # Build lookup: stripped_name → original_key
    stripped_map = {}
    for k in row.keys():
        if k is None: continue
        stripped_k = _strip_prefix(k)
        if stripped_k:
            stripped_map[stripped_k] = k

    for c in candidates:
        # Try exact match first
        if c in row:
            return c
        # Try stripped match
        stripped_c = _strip_prefix(c)
        if stripped_c in stripped_map:
            return stripped_map[stripped_c]
    return None


# ---------------------------------------------------------------------------
# CSV reader — handles Samsung's 2-row header format
# ---------------------------------------------------------------------------

def _read_samsung_csv(content: str) -> list[dict]:
    """
    Parse a Samsung Health CSV.
    Row 1: package metadata line (skip). Usually: "com.samsung.health.type,ver,..."
    Row 2: actual column headers (may have package prefixes)
    Row 3+: data

    Returns list of dicts keyed by the stripped column name AND original name.
    """
    lines = content.splitlines()
    if len(lines) < 2:
        return []

    # Find the real header row
    header_idx = 0
    for i, line in enumerate(lines[:5]):
        stripped = line.strip()
        if "," in stripped and not stripped.startswith("#"):
            parts = [p.strip() for p in stripped.split(",")]
            # Metadata row usually starts with "com.samsung" and has few columns
            if i == 0 and stripped.startswith("com.samsung") and len(parts) < 10:
                continue
            
            # Real headers usually have many columns or known keywords
            if len(parts) >= 2:
                header_idx = i
                break

    if header_idx >= len(lines):
        return []

    data_lines = lines[header_idx:]
    reader = csv.DictReader(data_lines)
    rows = list(reader)
    return rows


# ---------------------------------------------------------------------------
# SamsungHealthParser
# ---------------------------------------------------------------------------

class SamsungHealthParser:
    """
    Parse Samsung Health GDPR export data for S23 (no Galaxy Watch).

    Primary focus: step data as the continuous activity signal,
    including during the Mi Band gap period (Feb 2024 – Feb 2026).
    """

    def __init__(
        self,
        mi_band_gap_start: date = MI_BAND_GAP_START,
        mi_band_gap_end:   date = MI_BAND_GAP_END,
    ) -> None:
        self.mi_band_gap_start = mi_band_gap_start
        self.mi_band_gap_end   = mi_band_gap_end

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def parse(self, path: str | Path) -> SamsungReport:
        """
        Parse a Samsung Health export ZIP file or extracted folder.

        Args:
            path: path to .zip file OR extracted folder

        Returns:
            SamsungReport with all parsed data.
        """
        path = Path(path)
        if path.is_dir():
            return self._parse_folder(path)
        if path.suffix.lower() == ".zip":
            return self._parse_zip(path)
        raise ValueError(f"Expected .zip or directory, got: {path}")

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def _parse_zip(self, zip_path: Path) -> SamsungReport:
        report = SamsungReport()
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            for name in names:
                if not name.endswith(".csv"):
                    continue
                try:
                    content = zf.read(name).decode("utf-8-sig", errors="replace")
                    self._dispatch(name, content, report)
                except Exception as e:
                    report.parse_errors.append(f"Error reading {name}: {e}")
        self._post_process(report)
        return report

    def _parse_folder(self, folder: Path) -> SamsungReport:
        report = SamsungReport()
        for csv_file in folder.glob("*.csv"):
            try:
                content = csv_file.read_text(encoding="utf-8-sig", errors="replace")
                self._dispatch(csv_file.name, content, report)
            except Exception as e:
                report.parse_errors.append(f"Error reading {csv_file.name}: {e}")
        self._post_process(report)
        return report

    # ------------------------------------------------------------------
    # File dispatcher
    # ------------------------------------------------------------------

    def _dispatch(self, filename: str, content: str, report: SamsungReport) -> None:
        """Route a CSV file to the right parser based on filename."""
        fn = filename.lower()

        if "step_daily_trend" in fn:
            report.files_found.append("step_daily_trend")
            self._parse_step_daily_trend(content, report)

        elif "pedometer_day_summary" in fn:
            # Only use as fallback if no step_daily_trend data yet
            if not report.steps:
                report.files_found.append("pedometer_day_summary")
                self._parse_pedometer_day_summary(content, report)

        elif "exercise" in fn and "weather" not in fn and "goal" not in fn:
            report.files_found.append("exercise")
            self._parse_exercise(content, report)

        elif "activity.day_summary" in fn or "activity_level" in fn:
            report.files_found.append("activity_summary")
            self._parse_activity_summary(content, report)

        elif "weight" in fn and "goal" not in fn:
            report.files_found.append("weight")
            self._parse_weight(content, report)

        elif "water_intake" in fn:
            report.files_found.append("water_intake")
            self._parse_water(content, report)

    # ------------------------------------------------------------------
    # Step parsers
    # ------------------------------------------------------------------

    def _parse_step_daily_trend(self, content: str, report: SamsungReport) -> None:
        """
        Parse com.samsung.shealth.step_daily_trend.*.csv

        Key columns (after stripping prefix):
            day_time       — date of the record
            step_count     — steps for this source/day
            calorie        — calories burned
            distance       — distance in meters (or cm — see below)
            time_offset    — UTC offset string e.g. '+02:00'
            source_type    — 0=phone, 1=wearable

        Multiple rows per day (one per source device) → sum them.
        """
        rows = _read_samsung_csv(content)
        if not rows:
            return

        # Accumulate per-day across multiple source rows
        daily: dict[date, dict] = {}

        for row in rows:
            try:
                # Find date column
                date_key = _find_col(row, ["day_time", "create_time", "start_time", "date"])
                if not date_key:
                    continue

                offset_key = _find_col(row, ["time_offset"])
                offset_str = row.get(offset_key, "") if offset_key else ""

                dt = _parse_dt_samsung(row[date_key], offset_str)
                if not dt:
                    continue
                d = dt.date()

                step_key    = _find_col(row, ["step_count", "steps", "count"])
                cal_key     = _find_col(row, ["calorie", "calories"])
                dist_key    = _find_col(row, ["distance"])
                active_key  = _find_col(row, ["active_time", "run_step", "walk_step"])
                source_key  = _find_col(row, ["source_type", "deviceuuid", "device_uuid"])

                steps    = _safe_int(row.get(step_key, "0") if step_key else "0")
                calories = _safe_float(row.get(cal_key, "0") if cal_key else "0")
                distance = _safe_float(row.get(dist_key, "0") if dist_key else "0")
                source   = str(row.get(source_key, "phone") if source_key else "phone")

                # Samsung sometimes stores distance in cm — convert to meters
                if distance > 100000:
                    distance = distance / 100

                if steps == 0:
                    continue

                if d not in daily:
                    daily[d] = {
                        "steps":    0,
                        "calories": 0.0,
                        "distance": 0.0,
                        "active":   0,
                        "sources":  set(),
                    }

                # Use MAX not SUM — Samsung stores one row per source device
                # per day. Summing them doubles the real value.
                # The app itself shows the highest source reading, so we do too.
                daily[d]["steps"]    = max(daily[d]["steps"], steps)
                daily[d]["calories"] = max(daily[d]["calories"], calories)
                daily[d]["distance"] = max(daily[d]["distance"], distance)
                daily[d]["sources"].add(source)

            except Exception as e:
                report.parse_errors.append(f"step_daily_trend row: {e}")

        for d, vals in sorted(daily.items()):
            sources = vals["sources"]
            if len(sources) > 1:
                source_label = "merged"
            elif "0" in sources or "phone" in str(sources).lower():
                source_label = "phone"
            else:
                source_label = "wearable"

            report.steps.append(DailySteps(
                date=d,
                steps=vals["steps"],
                distance_meters=round(vals["distance"], 1),
                calories=round(vals["calories"], 1),
                active_time_min=vals["active"],
                source=source_label,
            ))

        logger.info(f"step_daily_trend: {len(daily)} days parsed")

    def _parse_pedometer_day_summary(self, content: str, report: SamsungReport) -> None:
        """
        Fallback: parse pedometer_day_summary if step_daily_trend not present.
        Simpler format, phone-only data.
        """
        rows = _read_samsung_csv(content)
        if not rows:
            return

        seen: set[date] = set()
        for row in rows:
            try:
                date_key = _find_col(row, ["create_time", "day_time", "date"])
                if not date_key:
                    continue

                offset_key = _find_col(row, ["time_offset"])
                offset_str = row.get(offset_key, "") if offset_key else ""

                dt = _parse_dt_samsung(row[date_key], offset_str)
                if not dt:
                    continue
                d = dt.date()

                if d in seen:
                    continue
                seen.add(d)

                step_key = _find_col(row, ["step_count", "steps"])
                dist_key = _find_col(row, ["distance"])
                cal_key  = _find_col(row, ["calorie", "calories"])

                steps = _safe_int(row.get(step_key, "0") if step_key else "0")
                if steps == 0:
                    continue

                dist = _safe_float(row.get(dist_key, "0") if dist_key else "0")
                if dist > 100000:
                    dist = dist / 100

                report.steps.append(DailySteps(
                    date=d,
                    steps=steps,
                    distance_meters=round(dist, 1),
                    calories=_safe_float(row.get(cal_key, "0") if cal_key else "0"),
                    active_time_min=0,
                    source="phone",
                ))
            except Exception as e:
                report.parse_errors.append(f"pedometer_day_summary row: {e}")

        logger.info(f"pedometer_day_summary: {len(seen)} days parsed")

    # ------------------------------------------------------------------
    # Exercise parser
    # ------------------------------------------------------------------

    def _parse_exercise(self, content: str, report: SamsungReport) -> None:
        """
        Parse com.samsung.shealth.exercise.*.csv

        Key columns: start_time, end_time, exercise_type,
                     calorie, distance, mean_heart_rate, max_heart_rate,
                     step_count, comment
        """
        rows = _read_samsung_csv(content)
        if not rows:
            return

        for row in rows:
            try:
                start_key  = _find_col(row, ["start_time"])
                end_key    = _find_col(row, ["end_time"])
                type_key   = _find_col(row, ["exercise_type", "type"])
                cal_key    = _find_col(row, ["calorie", "calories"])
                dist_key   = _find_col(row, ["distance"])
                hr_avg_key = _find_col(row, ["mean_heart_rate", "heart_rate_avg"])
                hr_max_key = _find_col(row, ["max_heart_rate", "heart_rate_max"])
                steps_key  = _find_col(row, ["step_count", "steps"])
                notes_key  = _find_col(row, ["comment", "notes"])
                offset_key = _find_col(row, ["time_offset"])

                if not start_key:
                    continue

                offset_str = row.get(offset_key, "") if offset_key else ""
                start_dt   = _parse_dt_samsung(row[start_key], offset_str)
                if not start_dt:
                    continue

                end_dt = None
                if end_key and row.get(end_key):
                    end_dt = _parse_dt_samsung(row[end_key], offset_str)

                duration_min = 0
                if end_dt and start_dt:
                    duration_min = max(0, int((end_dt - start_dt).total_seconds() / 60))

                exercise_type_raw = str(row.get(type_key, "10001") if type_key else "10001")
                exercise_type = EXERCISE_TYPE_MAP.get(exercise_type_raw.strip(), f"type_{exercise_type_raw}")

                dist = _safe_float(row.get(dist_key, "0") if dist_key else "0")
                if dist > 100000:
                    dist = dist / 100

                hr_avg = _safe_int(row.get(hr_avg_key, "0") if hr_avg_key else "0") or None
                hr_max = _safe_int(row.get(hr_max_key, "0") if hr_max_key else "0") or None
                steps  = _safe_int(row.get(steps_key, "0") if steps_key else "0") or None
                notes  = str(row.get(notes_key, "") if notes_key else "").strip() or None

                report.exercise.append(ExerciseSession(
                    date=start_dt.date(),
                    start=start_dt,
                    end=end_dt,
                    exercise_type=exercise_type,
                    duration_minutes=duration_min,
                    distance_meters=round(dist, 1),
                    calories=_safe_float(row.get(cal_key, "0") if cal_key else "0"),
                    mean_heart_rate=hr_avg,
                    max_heart_rate=hr_max,
                    steps=steps,
                    notes=notes,
                ))
            except Exception as e:
                report.parse_errors.append(f"exercise row: {e}")

        logger.info(f"exercise: {len(report.exercise)} sessions parsed")

    # ------------------------------------------------------------------
    # Activity summary parser
    # ------------------------------------------------------------------

    def _parse_activity_summary(self, content: str, report: SamsungReport) -> None:
        """Parse com.samsung.shealth.activity.day_summary.*.csv"""
        rows = _read_samsung_csv(content)
        if not rows:
            return

        seen: set[date] = set()
        for row in rows:
            try:
                date_key       = _find_col(row, ["day_time", "create_time", "date"])
                active_cal_key = _find_col(row, ["active_calorie", "active_calories"])
                total_cal_key  = _find_col(row, ["calorie", "total_calorie", "calories"])
                active_min_key = _find_col(row, ["active_time", "moderate_intensity", "active_minutes"])
                offset_key     = _find_col(row, ["time_offset"])

                if not date_key:
                    continue

                offset_str = row.get(offset_key, "") if offset_key else ""
                dt = _parse_dt_samsung(row[date_key], offset_str)
                if not dt:
                    continue
                d = dt.date()

                if d in seen:
                    continue
                seen.add(d)

                active_cal = _safe_float(row.get(active_cal_key, "0") if active_cal_key else "0")
                total_cal  = _safe_float(row.get(total_cal_key, "0") if total_cal_key else "0")

                # active_time in Samsung is stored in milliseconds
                active_ms  = _safe_float(row.get(active_min_key, "0") if active_min_key else "0")
                active_min = int(active_ms / 60000) if active_ms > 1000 else int(active_ms)

                report.activity.append(ActivityDay(
                    date=d,
                    active_calories=active_cal,
                    total_calories=total_cal,
                    active_minutes=active_min,
                ))
            except Exception as e:
                report.parse_errors.append(f"activity_summary row: {e}")

        logger.info(f"activity_summary: {len(seen)} days parsed")

    # ------------------------------------------------------------------
    # Weight parser
    # ------------------------------------------------------------------

    def _parse_weight(self, content: str, report: SamsungReport) -> None:
        """Parse com.samsung.health.weight.*.csv"""
        rows = _read_samsung_csv(content)
        if not rows:
            return

        for row in rows:
            try:
                date_key   = _find_col(row, ["create_time", "start_time", "date"])
                weight_key = _find_col(row, ["weight"])
                bmi_key    = _find_col(row, ["bmi"])
                fat_key    = _find_col(row, ["body_fat", "fat_mass"])
                offset_key = _find_col(row, ["time_offset"])

                if not date_key or not weight_key:
                    continue

                offset_str = row.get(offset_key, "") if offset_key else ""
                dt = _parse_dt_samsung(row[date_key], offset_str)
                if not dt:
                    continue

                weight = _safe_float(row.get(weight_key, "0"))
                if weight <= 0:
                    continue
                if weight > 500:
                    weight = weight / 1000   # grams to kg

                bmi = _safe_float(row.get(bmi_key, "0") if bmi_key else "0") or None
                fat = _safe_float(row.get(fat_key, "0") if fat_key else "0") or None

                report.weight.append(WeightEntry(
                    date=dt.date(),
                    weight_kg=round(weight, 2),
                    bmi=round(bmi, 1) if bmi else None,
                    body_fat=round(fat, 1) if fat else None,
                ))
            except Exception as e:
                report.parse_errors.append(f"weight row: {e}")

        logger.info(f"weight: {len(report.weight)} entries parsed")

    # ------------------------------------------------------------------
    # Water intake parser
    # ------------------------------------------------------------------

    def _parse_water(self, content: str, report: SamsungReport) -> None:
        """Parse com.samsung.health.water_intake.*.csv — aggregate per day."""
        rows = _read_samsung_csv(content)
        if not rows:
            return

        daily: dict[date, float] = {}
        for row in rows:
            try:
                date_key   = _find_col(row, ["start_time", "create_time"])
                amount_key = _find_col(row, ["amount", "water"])
                offset_key = _find_col(row, ["time_offset"])

                if not date_key or not amount_key:
                    continue

                offset_str = row.get(offset_key, "") if offset_key else ""
                dt = _parse_dt_samsung(row[date_key], offset_str)
                if not dt:
                    continue

                amount = _safe_float(row.get(amount_key, "0"))
                if amount > 0:
                    daily[dt.date()] = daily.get(dt.date(), 0.0) + amount
            except Exception as e:
                report.parse_errors.append(f"water row: {e}")

        for d, ml in sorted(daily.items()):
            report.water.append(WaterIntakeDay(date=d, ml=round(ml, 1)))

        logger.info(f"water_intake: {len(daily)} days parsed")

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _post_process(self, report: SamsungReport) -> None:
        """
        After parsing all files:
        1. Deduplicate step records (same date from multiple parsers)
        2. Sort everything by date
        3. Add Mi Band gap annotation
        4. Log summary
        """
        # Deduplicate steps — keep the one with higher step count per day
        step_by_date: dict[date, DailySteps] = {}
        for s in report.steps:
            if s.date not in step_by_date or s.steps > step_by_date[s.date].steps:
                step_by_date[s.date] = s
        report.steps = sorted(step_by_date.values(), key=lambda s: s.date)

        # Sort everything
        report.exercise = sorted(report.exercise, key=lambda e: e.date)
        report.activity = sorted(report.activity, key=lambda a: a.date)
        report.weight   = sorted(report.weight, key=lambda w: w.date)
        report.water    = sorted(report.water, key=lambda w: w.date)

        # Add Mi Band gap annotation
        gap_steps = [s for s in report.steps
                     if self.mi_band_gap_start <= s.date <= self.mi_band_gap_end]
        if gap_steps:
            report.notes.append(DataNote(
                date_range_start=self.mi_band_gap_start,
                date_range_end=self.mi_band_gap_end,
                note_type="mi_band_gap",
                message=(
                    f"Mi Band 5 not worn during this period. "
                    f"Step data ({len(gap_steps)} days) is from S23 phone pedometer only. "
                    f"No HR, sleep stage or SpO2 data available for this period."
                ),
            ))

        logger.info(report.summary())


# ---------------------------------------------------------------------------
# Merge helper — combine Samsung + Zepp into one unified daily timeline
# ---------------------------------------------------------------------------

def merge_daily_timelines(
    samsung_report: SamsungReport,
    zepp_report,        # ZeppReport — avoid circular import, typed loosely
) -> list[dict]:
    """
    Merge Samsung Health and Zepp Life daily summaries into one unified
    timeline. Samsung provides steps; Zepp provides HR, sleep, SpO2.

    During the Mi Band gap (Feb 2024 – Feb 2026):
        - Steps come from Samsung (phone pedometer)
        - HR, sleep, SpO2 = None (band not worn)

    Returns list of dicts sorted by date, one entry per day.
    """
    samsung_by_date = {d["date"]: d for d in samsung_report.daily_summaries()}
    zepp_by_date    = {d["date"]: d for d in zepp_report.daily_summaries()}

    all_dates = sorted(set(samsung_by_date) | set(zepp_by_date))
    merged = []

    for d_str in all_dates:
        s = samsung_by_date.get(d_str, {})
        z = zepp_by_date.get(d_str, {})
        in_gap = z.get("in_gap", False)

        merged.append({
            "date":            d_str,
            "in_mi_band_gap":  in_gap,
            # Steps: prefer Samsung (always from phone), fall back to Zepp
            "steps":           s.get("steps") or z.get("steps"),
            "step_source":     "samsung" if s.get("steps") else ("zepp" if z.get("steps") else None),
            "distance_m":      s.get("distance_m") or z.get("distance_m"),
            "calories":        s.get("step_calories") or z.get("calories"),
            "active_minutes":  s.get("active_time_min") or z.get("active_minutes"),
            # Wearable data — from Zepp only (Mi Band 5)
            "resting_hr":      z.get("resting_hr"),
            "sleep_total_min": z.get("sleep_total_min"),
            "sleep_deep_min":  z.get("sleep_deep_min"),
            "sleep_quality":   z.get("sleep_quality"),
            "avg_spo2":        z.get("avg_spo2"),
            "avg_stress":      z.get("avg_stress"),
        })

    return merged


# ---------------------------------------------------------------------------
# CLI — python samsung_parser.py path/to/export.zip [--json]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python samsung_parser.py <path_to_zip_or_folder> [--json]")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    report = SamsungHealthParser().parse(sys.argv[1])

    print("\n" + report.summary())

    gap_comp = report.gap_step_vs_normal_comparison()
    if gap_comp:
        print(f"\n{'='*50}")
        print("STEP ACTIVITY COMPARISON (Mi Band gap period):")
        for k, v in gap_comp.items():
            print(f"  {k}: {v}")

    print(f"\n{'='*50}")
    print("RECENT STEPS (last 10 days with data):")
    for s in report.steps[-10:]:
        gap_marker = " [gap]" if MI_BAND_GAP_START <= s.date <= MI_BAND_GAP_END else ""
        print(f"  {s.date}  {s.steps:>7,} steps  {s.distance_meters/1000:.1f} km"
              f"  ({s.source}){gap_marker}")

    if report.exercise:
        print(f"\n{'='*50}")
        print(f"EXERCISE SESSIONS (last 5):")
        for e in report.exercise[-5:]:
            print(f"  {e.date}  {e.exercise_type:<15}  {e.duration_minutes} min"
                  f"  {e.distance_meters/1000:.1f} km  {int(e.calories)} kcal")

    if report.parse_errors:
        print(f"\nParse errors ({len(report.parse_errors)}):")
        for err in report.parse_errors[:10]:
            print(f"  {err}")

    if "--json" in sys.argv:
        print("\n--- JSON output ---")
        print(json.dumps(report.to_dict(), indent=2, default=str))
