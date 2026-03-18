"""
ZeppParser — Zepp Life (formerly Mi Fit) GDPR export parser.
Designed for Mi Band 5 data exported from Zepp Life app.

Export instructions:
    Zepp Life app → Profile (bottom right) → Privacy and Account
    → Download Personal Data → request export → unzip the received file

Export format: ZIP containing CSV files, one per data type.

Key files parsed:
    HEARTRATE.csv       — continuous heart rate readings
    SLEEP.csv           — nightly sleep sessions with stage breakdown
    ACTIVITY_STAGE.csv  — per-minute activity level (steps proxy)
    SPORT.csv           — workout sessions
    SPO2.csv            — blood oxygen readings
    STRESS.csv          — stress score readings
    BODY_WEIGHT.csv     — weight / BMI entries

Gap handling:
    The parser is aware that data may be missing for extended periods
    (e.g. Feb 2024 – Feb 2026 when the band was not worn).
    All summary methods exclude gap periods from averages and trend
    calculations. Gap periods are clearly flagged in the output.

Usage:
    parser = ZeppParser()
    report = parser.parse("path/to/zepp_export.zip")

    # Or parse an already-extracted folder
    report = parser.parse_folder("path/to/extracted/")

    print(report.summary())
    data = report.to_dict()            # for DB storage
    daily = report.daily_summaries()   # one row per day
"""

import csv
import io
import logging
import pyzipper
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Known gap: band not worn between these dates (inclusive)
DEFAULT_GAP_START = date(2024, 2, 1)
DEFAULT_GAP_END = date(2025, 2, 1)

# Mi Band 5 resting heart rate plausible range
HR_MIN_PLAUSIBLE = 30
HR_MAX_PLAUSIBLE = 220

# SpO2 plausible range
SPO2_MIN_PLAUSIBLE = 70
SPO2_MAX_PLAUSIBLE = 100

# Sleep stage codes used in Zepp export
SLEEP_STAGE_DEEP = 4  # deep sleep (NREM3)
SLEEP_STAGE_LIGHT = 1  # light sleep (NREM1/2)
SLEEP_STAGE_REM = 5  # REM sleep
SLEEP_STAGE_AWAKE = 6  # awake during night
SLEEP_STAGE_UNKNOWN = 0

# Stress categories
STRESS_LOW = (0, 25)
STRESS_MODERATE = (25, 50)
STRESS_HIGH = (50, 75)
STRESS_VERY_HIGH = (75, 100)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class HeartRateReading:
    timestamp: datetime
    bpm: int
    is_resting: bool = False  # True if measured during low-activity period


@dataclass
class SleepSession:
    date: date  # night date (the date the person went to bed)
    start: datetime
    end: datetime
    total_minutes: int
    deep_minutes: int
    light_minutes: int
    rem_minutes: int
    awake_minutes: int
    efficiency: Optional[float]  # 0-100%, None if unavailable

    @property
    def duration_hours(self) -> float:
        return self.total_minutes / 60

    @property
    def sleep_quality(self) -> str:
        """Simple quality label based on duration and deep sleep ratio."""
        if self.total_minutes < 300:
            return "poor"
        if self.total_minutes < 360:
            return "fair"
        deep_ratio = self.deep_minutes / max(self.total_minutes, 1)
        if deep_ratio >= 0.20 and self.total_minutes >= 420:
            return "good"
        if self.total_minutes >= 420:
            return "fair"
        return "fair"


@dataclass
class ActivityDay:
    date: date
    steps: int
    distance_meters: float
    calories: int
    active_minutes: int  # minutes with activity level >= 3


@dataclass
class WorkoutSession:
    date: date
    start: datetime
    end: datetime
    sport_type: str  # "running", "walking", "cycling", etc.
    duration_minutes: int
    calories: int
    distance_meters: float
    avg_heart_rate: Optional[int]
    max_heart_rate: Optional[int]
    steps: Optional[int]


@dataclass
class SpO2Reading:
    timestamp: datetime
    spo2_pct: float


@dataclass
class StressReading:
    timestamp: datetime
    stress_score: int  # 0-100


@dataclass
class WeightEntry:
    date: date
    weight_kg: float
    bmi: Optional[float]


@dataclass
class DataGap:
    """Represents a period where the band was not worn."""

    start: date
    end: date
    reason: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days


@dataclass
class ZeppReport:
    """Full parsed result from a Zepp Life export."""

    heart_rate: list[HeartRateReading] = field(default_factory=list)
    sleep: list[SleepSession] = field(default_factory=list)
    activity: list[ActivityDay] = field(default_factory=list)
    workouts: list[WorkoutSession] = field(default_factory=list)
    spo2: list[SpO2Reading] = field(default_factory=list)
    stress: list[StressReading] = field(default_factory=list)
    weight: list[WeightEntry] = field(default_factory=list)
    gaps: list[DataGap] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    files_found: list[str] = field(default_factory=list)

    def date_range(self) -> tuple[Optional[date], Optional[date]]:
        """Earliest and latest dates across all data types."""
        all_dates: list[date] = []
        for r in self.heart_rate:
            all_dates.append(r.timestamp.date())
        for s in self.sleep:
            all_dates.append(s.date)
        for a in self.activity:
            all_dates.append(a.date)
        if not all_dates:
            return None, None
        return min(all_dates), max(all_dates)

    def resting_hr_series(self) -> list[tuple[date, float]]:
        """
        Daily resting heart rate — median of readings below 80 bpm
        (low-activity proxy), excluding gap periods.
        """
        by_day: dict[date, list[int]] = {}
        for r in self.heart_rate:
            d = r.timestamp.date()
            if _in_gap(d, self.gaps):
                continue
            if r.bpm <= 80:
                by_day.setdefault(d, []).append(r.bpm)
        result = []
        for d in sorted(by_day):
            if len(by_day[d]) >= 3:  # need at least 3 readings for reliability
                result.append((d, round(median(by_day[d]), 1)))
        return result

    def avg_resting_hr(self, days: int = 30) -> Optional[float]:
        """Average resting HR over the last N days (excluding gaps)."""
        series = self.resting_hr_series()
        if not series:
            return None
        cutoff = series[-1][0] - timedelta(days=days)
        recent = [v for d, v in series if d >= cutoff]
        return round(mean(recent), 1) if recent else None

    def avg_sleep_duration(self, days: int = 30) -> Optional[float]:
        """Average sleep duration in hours over recent N days (excluding gaps)."""
        cutoff = date.today() - timedelta(days=days)
        sessions = [
            s for s in self.sleep if s.date >= cutoff and not _in_gap(s.date, self.gaps)
        ]
        if not sessions:
            return None
        return round(mean(s.duration_hours for s in sessions), 2)

    def avg_steps(self, days: int = 30) -> Optional[float]:
        """Average daily steps over recent N days (excluding gaps)."""
        cutoff = date.today() - timedelta(days=days)
        days_data = [
            a
            for a in self.activity
            if a.date >= cutoff and not _in_gap(a.date, self.gaps)
        ]
        if not days_data:
            return None
        return round(mean(a.steps for a in days_data), 0)

    def avg_spo2(self, days: int = 30) -> Optional[float]:
        """Average SpO2 % over recent N days."""
        cutoff = date.today() - timedelta(days=days)
        readings = [
            r
            for r in self.spo2
            if r.timestamp.date() >= cutoff
            and not _in_gap(r.timestamp.date(), self.gaps)
        ]
        if not readings:
            return None
        return round(mean(r.spo2_pct for r in readings), 1)

    def latest_weight(self) -> Optional[WeightEntry]:
        """Most recent weight entry."""
        if not self.weight:
            return None
        return sorted(self.weight, key=lambda w: w.date)[-1]

    def daily_summaries(self) -> list[dict]:
        """
        One dict per day merging all data types.
        Used for DB storage and trend charts.
        """
        all_dates = set()
        for r in self.heart_rate:
            all_dates.add(r.timestamp.date())
        for s in self.sleep:
            all_dates.add(s.date)
        for a in self.activity:
            all_dates.add(a.date)

        activity_by_date = {a.date: a for a in self.activity}
        sleep_by_date = {s.date: s for s in self.sleep}

        summaries = []
        for d in sorted(all_dates):
            in_gap = _in_gap(d, self.gaps)
            hr_readings = [
                r.bpm
                for r in self.heart_rate
                if r.timestamp.date() == d and r.bpm <= 80
            ]
            spo2_readings = [r.spo2_pct for r in self.spo2 if r.timestamp.date() == d]
            stress_readings = [
                r.stress_score for r in self.stress if r.timestamp.date() == d
            ]
            act = activity_by_date.get(d)
            slp = sleep_by_date.get(d)

            summaries.append(
                {
                    "date": d.isoformat(),
                    "in_gap": in_gap,
                    "resting_hr": (
                        round(median(hr_readings), 1) if hr_readings else None
                    ),
                    "steps": act.steps if act else None,
                    "distance_m": act.distance_meters if act else None,
                    "calories": act.calories if act else None,
                    "active_minutes": act.active_minutes if act else None,
                    "sleep_total_min": slp.total_minutes if slp else None,
                    "sleep_deep_min": slp.deep_minutes if slp else None,
                    "sleep_light_min": slp.light_minutes if slp else None,
                    "sleep_rem_min": slp.rem_minutes if slp else None,
                    "sleep_quality": slp.sleep_quality if slp else None,
                    "avg_spo2": (
                        round(mean(spo2_readings), 1) if spo2_readings else None
                    ),
                    "avg_stress": (
                        round(mean(stress_readings), 1) if stress_readings else None
                    ),
                }
            )
        return summaries

    def summary(self) -> str:
        """Human-readable summary string for logging / debugging."""
        start, end = self.date_range()
        lines = [
            f"Zepp Life Export Summary",
            f"{'='*50}",
            f"Data range  : {start} → {end}",
            f"HR readings : {len(self.heart_rate)}",
            f"Sleep nights: {len(self.sleep)}",
            f"Activity days:{len(self.activity)}",
            f"Workouts    : {len(self.workouts)}",
            f"SpO2 readings:{len(self.spo2)}",
            f"Stress reads: {len(self.stress)}",
            f"Weight entries:{len(self.weight)}",
            f"Files found : {', '.join(self.files_found)}",
        ]
        if self.gaps:
            for g in self.gaps:
                lines.append(
                    f"Gap detected: {g.start} → {g.end} ({g.days} days) — {g.reason}"
                )
        avg_hr = self.avg_resting_hr()
        if avg_hr:
            lines.append(f"Avg resting HR (30d): {avg_hr} bpm")
        avg_sleep = self.avg_sleep_duration()
        if avg_sleep:
            lines.append(f"Avg sleep (30d): {avg_sleep:.1f} h")
        avg_steps = self.avg_steps()
        if avg_steps:
            lines.append(f"Avg steps (30d): {int(avg_steps):,}")
        w = self.latest_weight()
        if w:
            lines.append(f"Latest weight: {w.weight_kg} kg (BMI: {w.bmi})")
        if self.parse_errors:
            lines.append(f"Parse errors: {len(self.parse_errors)}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Full serialization for API responses or DB storage."""
        return {
            "date_range": {
                "start": (
                    self.date_range()[0].isoformat() if self.date_range()[0] else None
                ),
                "end": (
                    self.date_range()[1].isoformat() if self.date_range()[1] else None
                ),
            },
            "gaps": [
                {
                    "start": g.start.isoformat(),
                    "end": g.end.isoformat(),
                    "days": g.days,
                    "reason": g.reason,
                }
                for g in self.gaps
            ],
            "aggregates": {
                "avg_resting_hr_30d": self.avg_resting_hr(30),
                "avg_sleep_hours_30d": self.avg_sleep_duration(30),
                "avg_steps_30d": self.avg_steps(30),
                "avg_spo2_30d": self.avg_spo2(30),
                "latest_weight_kg": (
                    self.latest_weight().weight_kg if self.latest_weight() else None
                ),
                "latest_bmi": (
                    self.latest_weight().bmi if self.latest_weight() else None
                ),
                "total_workouts": len(self.workouts),
            },
            "daily_summaries": self.daily_summaries(),
            "files_found": self.files_found,
            "parse_errors": self.parse_errors,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _in_gap(d: date, gaps: list[DataGap]) -> bool:
    return any(g.start <= d <= g.end for g in gaps)


def _parse_dt(value: str, fmt_candidates: list[str]) -> Optional[datetime]:
    """Try multiple datetime formats, return None if all fail."""
    value = value.strip()
    for fmt in fmt_candidates:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_date(value: str) -> Optional[date]:
    dt = _parse_dt(value, ["%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"])
    return dt.date() if dt else None


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value.strip()))
    except (ValueError, AttributeError):
        return default


def _safe_float(value: str, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return default


def _find_column(header: list[str], candidates: list[str]) -> Optional[str]:
    """Case-insensitive column name lookup with fuzzy matching for BOM/spaces."""
    header_map = {h.lower().strip().replace("\ufeff", ""): h for h in header}
    for c in candidates:
        c_low = c.lower().strip()
        if c_low in header_map:
            return header_map[c_low]
        # Also try direct contains for cases like "time (UTC)"
        for h_low, h_orig in header_map.items():
            if c_low in h_low:
                return h_orig
    return None


def _detect_gaps(
    records_dates: list[date],
    known_gap_start: date = DEFAULT_GAP_START,
    known_gap_end: date = DEFAULT_GAP_END,
    auto_gap_days: int = 30,
) -> list[DataGap]:
    """
    Detect data gaps:
    1. The known band-not-worn period (Feb 2024 – Feb 2026).
    2. Any other period with no data for >30 consecutive days.
    """
    gaps: list[DataGap] = []

    # Known gap
    gaps.append(
        DataGap(
            start=known_gap_start,
            end=known_gap_end,
            reason="Mi Band 5 not worn (known gap)",
        )
    )

    # Auto-detect additional gaps
    if len(records_dates) < 2:
        return gaps
    sorted_dates = sorted(set(records_dates))
    for i in range(1, len(sorted_dates)):
        delta = (sorted_dates[i] - sorted_dates[i - 1]).days
        if delta > auto_gap_days:
            gap_start = sorted_dates[i - 1] + timedelta(days=1)
            gap_end = sorted_dates[i] - timedelta(days=1)
            # Don't double-report if this overlaps the known gap
            if not (gap_start >= known_gap_start and gap_end <= known_gap_end):
                gaps.append(
                    DataGap(
                        start=gap_start,
                        end=gap_end,
                        reason=f"No data for {delta} days (auto-detected)",
                    )
                )
    return gaps


# ---------------------------------------------------------------------------
# Sport type mapping
# ---------------------------------------------------------------------------

SPORT_TYPE_MAP = {
    "1": "running",
    "2": "walking",
    "4": "cycling",
    "6": "elliptical",
    "8": "swimming",
    "9": "yoga",
    "11": "treadmill",
    "16": "strength",
    "112": "hiking",
}


# ---------------------------------------------------------------------------
# ZeppParser
# ---------------------------------------------------------------------------


class ZeppParser:
    """
    Parse Zepp Life (formerly Mi Fit) GDPR export data.

    Handles ZIP archives or pre-extracted folders.
    Gracefully skips missing files (not all users have all data types).
    Gap-aware: data from the known non-wearing period is flagged but kept.
    """

    # datetime formats seen in different Zepp export versions
    DT_FORMATS = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S%z",
    ]

    def __init__(
        self,
        gap_start: date = DEFAULT_GAP_START,
        gap_end: date = DEFAULT_GAP_END,
    ) -> None:
        self.gap_start = gap_start
        self.gap_end = gap_end

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def parse(self, path: str | Path, password: str = None) -> ZeppReport:
        """
        Parse a Zepp Life export ZIP file or extracted folder.

        Args:
            path: path to the .zip file OR an extracted folder
            password: ZIP password if the export is encrypted (Zepp sends
                      the password in the confirmation email)

        Returns:
            ZeppReport with all parsed data and gap annotations.
        """
        path = Path(path)
        if path.is_dir():
            return self.parse_folder(path)
        if path.suffix.lower() == ".zip":
            return self._parse_zip(path, password=password)
        raise ValueError(f"Expected a .zip file or directory, got: {path}")

    def parse_folder(self, folder: str | Path) -> ZeppReport:
        """Parse from an already-extracted folder."""
        folder = Path(folder)
        report = ZeppReport()
        self._parse_all(report, file_reader=self._folder_reader(folder))
        return report

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _parse_zip(self, zip_path: Path, password: str = None) -> ZeppReport:
        report = ZeppReport()
        pwd_bytes = password.encode("utf-8") if password else None
        with pyzipper.AESZipFile(zip_path, "r") as zf:
            if pwd_bytes:
                zf.setpassword(pwd_bytes)
            self._parse_all(report, file_reader=self._zip_reader(zf, pwd_bytes))
        return report

    def _parse_all(self, report: ZeppReport, file_reader) -> None:
        """Try to parse each known file type; skip gracefully if missing."""
        parsers = {
            "HEARTRATE": self._parse_heart_rate,
            "SLEEP": self._parse_sleep,
            "ACTIVITY_STAGE": self._parse_activity,
            "SPORT": self._parse_workouts,
            "SPO2": self._parse_spo2,
            "STRESS": self._parse_stress,
            "BODY_WEIGHT": self._parse_weight,
        }
        for key, parser_fn in parsers.items():
            content = file_reader(key)
            # Special case for heart rate which sometimes uses HEARTRATE_AUTO
            if key == "HEARTRATE" and content is None:
                content = file_reader("HEARTRATE_AUTO")

            if content is not None:
                report.files_found.append(key)
                try:
                    parser_fn(content, report)
                except Exception as e:
                    msg = f"Error parsing {key}: {e}"
                    logger.error(msg)
                    report.parse_errors.append(msg)
            else:
                logger.info(f"File {key} not found in export — skipping")

        # Detect gaps from all date records
        all_dates = (
            [r.timestamp.date() for r in report.heart_rate]
            + [s.date for s in report.sleep]
            + [a.date for a in report.activity]
        )
        report.gaps = _detect_gaps(all_dates, self.gap_start, self.gap_end)

        logger.info(report.summary())

    # ------------------------------------------------------------------
    # File readers
    # ------------------------------------------------------------------

    def _folder_reader(self, folder: Path):
        """Returns a callable that looks up CSV files by key name in folder."""

        def reader(key: str) -> Optional[str]:
            # Try exact name and common variations
            candidates = [
                folder / f"{key}.csv",
                folder / f"{key.lower()}.csv",
                *folder.glob(f"*{key}*.csv"),
            ]
            for c in candidates:
                if c.exists():
                    return c.read_text(encoding="utf-8", errors="replace")
            return None

        return reader

    def _zip_reader(self, zf: pyzipper.AESZipFile, pwd_bytes: bytes = None):
        """Returns a callable that looks up CSV files by key name in ZIP."""
        names = zf.namelist()

        def reader(key: str) -> Optional[str]:
            for name in names:
                # Zepp export sometimes wraps files in a HEALTH_DATA/ directory
                clean_name = name.split("/")[-1]
                if key.upper() in clean_name.upper() and name.endswith(".csv"):
                    with zf.open(name, pwd=pwd_bytes) as f:
                        return f.read().decode("utf-8", errors="replace")
            return None

        return reader

    # ------------------------------------------------------------------
    # Individual file parsers
    # ------------------------------------------------------------------

    def _csv_rows(self, content: str) -> tuple[list[str], list[dict]]:
        """Parse CSV content, return (header, rows). Skips comment/metadata rows."""
        if not content:
            return [], []
        # Handle BOM if present in the string
        if content.startswith("\ufeff"):
            content = content.lstrip("\ufeff")

        lines = content.splitlines()
        # Zepp sometimes puts metadata in the first 1-2 rows before the header
        # Find the header row (first row that contains recognizable column names)
        header_idx = 0
        for i, line in enumerate(lines):
            clean_line = line.lower().strip().replace("\ufeff", "")
            if "," in clean_line and any(
                kw in clean_line
                for kw in [
                    "date",
                    "time",
                    "heart",
                    "step",
                    "sleep",
                    "stress",
                    "spo2",
                    "weight",
                ]
            ):
                header_idx = i
                break

        reader = csv.DictReader(lines[header_idx:])
        rows = list(reader)
        header = reader.fieldnames or []
        return [h.strip() for h in header], rows

    def _parse_heart_rate(self, content: str, report: ZeppReport) -> None:
        """
        Parse HEARTRATE.csv
        Expected columns: date, time, heartRate (or heart_rate, bpm, value)
        """
        header, rows = self._csv_rows(content)
        date_col = _find_column(header, ["date", "Date"])
        time_col = _find_column(header, ["time", "Time"])
        hr_col = _find_column(
            header,
            [
                "heartRate",
                "heart_rate",
                "bpm",
                "value",
                "HeartRate",
                "heart_rate_value",
            ],
        )

        if not hr_col:
            report.parse_errors.append("HEARTRATE: could not find heart rate column")
            return

        for row in rows:
            try:
                raw_dt = f"{row.get(date_col, '')} {row.get(time_col, '')}".strip()
                dt = _parse_dt(raw_dt, self.DT_FORMATS)
                if not dt:
                    # Try date-only
                    dt_date = _parse_date(row.get(date_col, ""))
                    if dt_date:
                        dt = datetime(dt_date.year, dt_date.month, dt_date.day)
                    else:
                        continue

                bpm = _safe_int(row.get(hr_col, "0"))
                if not (HR_MIN_PLAUSIBLE <= bpm <= HR_MAX_PLAUSIBLE):
                    continue  # filter implausible readings

                report.heart_rate.append(
                    HeartRateReading(
                        timestamp=dt,
                        bpm=bpm,
                    )
                )
            except Exception as e:
                report.parse_errors.append(f"HEARTRATE row error: {e}")

        logger.info(f"Heart rate: {len(report.heart_rate)} readings parsed")

    def _parse_sleep(self, content: str, report: ZeppReport) -> None:
        """
        Parse SLEEP.csv
        Expected columns: date, start, stop/end, deepSleepTime, shallowSleepTime,
                          REMTime, wakeTime (all in minutes)
        """
        header, rows = self._csv_rows(content)

        date_col = _find_column(header, ["date", "Date", "night_date"])
        start_col = _find_column(header, ["start", "startTime", "start_time"])
        end_col = _find_column(
            header, ["stop", "end", "endTime", "end_time", "stopTime"]
        )
        deep_col = _find_column(
            header, ["deepSleepTime", "deep_sleep", "deep", "deepTime"]
        )
        light_col = _find_column(
            header, ["shallowSleepTime", "light_sleep", "light", "shallowTime"]
        )
        rem_col = _find_column(header, ["REMTime", "rem_sleep", "rem", "remTime"])
        wake_col = _find_column(header, ["wakeTime", "wake", "awake", "awakeTimes"])
        eff_col = _find_column(
            header, ["efficiency", "sleepEfficiency", "sleep_efficiency"]
        )

        for row in rows:
            try:
                # Date of the sleep night
                date_str = row.get(date_col, "") if date_col else ""
                night_date = _parse_date(date_str)
                if not night_date:
                    continue

                # Start / end times
                start_str = row.get(start_col, "") if start_col else ""
                end_str = row.get(end_col, "") if end_col else ""
                start_dt = _parse_dt(start_str, self.DT_FORMATS)
                end_dt = _parse_dt(end_str, self.DT_FORMATS)

                # Stage durations in minutes
                deep = _safe_int(row.get(deep_col, "0") if deep_col else "0")
                light = _safe_int(row.get(light_col, "0") if light_col else "0")
                rem = _safe_int(row.get(rem_col, "0") if rem_col else "0")
                wake = _safe_int(row.get(wake_col, "0") if wake_col else "0")
                total = deep + light + rem + wake

                # If total is 0 but we have start/end, calculate from them
                if total == 0 and start_dt and end_dt:
                    total = int((end_dt - start_dt).total_seconds() / 60)

                if total < 30:  # skip implausible sessions < 30 min
                    continue

                efficiency = _safe_float(row.get(eff_col, "") if eff_col else "")

                report.sleep.append(
                    SleepSession(
                        date=night_date,
                        start=start_dt
                        or datetime(
                            night_date.year, night_date.month, night_date.day, 23, 0
                        ),
                        end=end_dt
                        or datetime(
                            night_date.year, night_date.month, night_date.day, 7, 0
                        ),
                        total_minutes=total,
                        deep_minutes=deep,
                        light_minutes=light,
                        rem_minutes=rem,
                        awake_minutes=wake,
                        efficiency=efficiency,
                    )
                )
            except Exception as e:
                report.parse_errors.append(f"SLEEP row error: {e}")

        logger.info(f"Sleep: {len(report.sleep)} sessions parsed")

    def _parse_activity(self, content: str, report: ZeppReport) -> None:
        """
        Parse ACTIVITY_STAGE.csv (per-minute activity level)
        Aggregates to daily summaries.
        Expected columns: date, time, value (activity level 1-5)
                          or: date, steps, distance, calories
        """
        header, rows = self._csv_rows(content)

        date_col = _find_column(header, ["date", "Date"])
        steps_col = _find_column(header, ["steps", "step", "Steps", "totalStep"])
        dist_col = _find_column(header, ["distance", "Distance", "dis"])
        cal_col = _find_column(header, ["calories", "calorie", "Calories", "cal"])
        val_col = _find_column(
            header,
            ["value", "level", "activityLevel", "activity_level", "activity_stage"],
        )

        # Detect format: aggregated daily vs per-minute stages
        is_daily = steps_col is not None

        if is_daily:
            # Direct daily aggregation format
            for row in rows:
                try:
                    d = _parse_date(row.get(date_col, "") if date_col else "")
                    if not d:
                        continue
                    report.activity.append(
                        ActivityDay(
                            date=d,
                            steps=_safe_int(
                                row.get(steps_col, "0") if steps_col else "0"
                            ),
                            distance_meters=_safe_float(
                                row.get(dist_col, "0") if dist_col else "0"
                            )
                            or 0.0,
                            calories=_safe_int(
                                row.get(cal_col, "0") if cal_col else "0"
                            ),
                            active_minutes=0,  # not available in daily format
                        )
                    )
                except Exception as e:
                    report.parse_errors.append(f"ACTIVITY row error: {e}")
        else:
            # Per-minute stage format — aggregate to daily
            daily: dict[date, dict] = {}
            for row in rows:
                try:
                    d = _parse_date(row.get(date_col, "") if date_col else "")
                    if not d:
                        continue
                    level = _safe_int(row.get(val_col, "0") if val_col else "0")
                    entry = daily.setdefault(
                        d, {"steps": 0, "dist": 0.0, "cal": 0, "active": 0}
                    )
                    if level >= 3:
                        entry["active"] += 1
                    # steps/dist/cal not available in stage format
                except Exception as e:
                    report.parse_errors.append(f"ACTIVITY_STAGE row error: {e}")

            for d, vals in sorted(daily.items()):
                report.activity.append(
                    ActivityDay(
                        date=d,
                        steps=vals["steps"],
                        distance_meters=vals["dist"],
                        calories=vals["cal"],
                        active_minutes=vals["active"],
                    )
                )

        logger.info(f"Activity: {len(report.activity)} days parsed")

    def _parse_workouts(self, content: str, report: ZeppReport) -> None:
        """
        Parse SPORT.csv (workout sessions)
        """
        header, rows = self._csv_rows(content)

        date_col = _find_column(header, ["date", "Date", "start_time"])
        start_col = _find_column(header, ["start", "startTime", "start_time"])
        end_col = _find_column(header, ["stop", "end", "endTime", "end_time"])
        type_col = _find_column(header, ["type", "sportType", "sport_type", "mode"])
        cal_col = _find_column(header, ["calories", "calorie"])
        dist_col = _find_column(header, ["distance", "dis"])
        avghr_col = _find_column(
            header, ["avgHeartRate", "avg_heart_rate", "averageHeartRate"]
        )
        maxhr_col = _find_column(header, ["maxHeartRate", "max_heart_rate"])
        steps_col = _find_column(header, ["steps", "totalStep"])

        for row in rows:
            try:
                start_str = (
                    row.get(start_col, "") if start_col else row.get(date_col, "")
                )
                start_dt = _parse_dt(start_str, self.DT_FORMATS)
                if not start_dt:
                    continue

                end_str = row.get(end_col, "") if end_col else ""
                end_dt = _parse_dt(end_str, self.DT_FORMATS)

                duration = 0
                if end_dt and start_dt:
                    duration = int((end_dt - start_dt).total_seconds() / 60)

                sport_raw = row.get(type_col, "0") if type_col else "0"
                sport_type = SPORT_TYPE_MAP.get(sport_raw.strip(), f"sport_{sport_raw}")

                dist_raw = (
                    _safe_float(row.get(dist_col, "0") if dist_col else "0") or 0.0
                )
                # Distance is sometimes in cm, sometimes in meters
                if dist_raw > 100000:  # likely in cm
                    dist_raw = dist_raw / 100

                report.workouts.append(
                    WorkoutSession(
                        date=start_dt.date(),
                        start=start_dt,
                        end=end_dt or start_dt,
                        sport_type=sport_type,
                        duration_minutes=duration,
                        calories=_safe_int(row.get(cal_col, "0") if cal_col else "0"),
                        distance_meters=dist_raw,
                        avg_heart_rate=_safe_int(
                            row.get(avghr_col, "0") if avghr_col else "0"
                        )
                        or None,
                        max_heart_rate=_safe_int(
                            row.get(maxhr_col, "0") if maxhr_col else "0"
                        )
                        or None,
                        steps=_safe_int(row.get(steps_col, "0") if steps_col else "0")
                        or None,
                    )
                )
            except Exception as e:
                report.parse_errors.append(f"SPORT row error: {e}")

        logger.info(f"Workouts: {len(report.workouts)} sessions parsed")

    def _parse_spo2(self, content: str, report: ZeppReport) -> None:
        """Parse SPO2.csv — blood oxygen readings."""
        header, rows = self._csv_rows(content)

        date_col = _find_column(header, ["date", "Date"])
        time_col = _find_column(header, ["time", "Time"])
        val_col = _find_column(
            header, ["spo2", "SpO2", "value", "bloodOxygen", "blood_oxygen"]
        )

        if not val_col:
            report.parse_errors.append("SPO2: could not find SpO2 value column")
            return

        for row in rows:
            try:
                raw_dt = f"{row.get(date_col, '')} {row.get(time_col, '')}".strip()
                dt = _parse_dt(raw_dt, self.DT_FORMATS)
                if not dt:
                    d = _parse_date(row.get(date_col, ""))
                    if d:
                        dt = datetime(d.year, d.month, d.day)
                    else:
                        continue

                val = _safe_float(row.get(val_col, ""))
                if val is None or not (SPO2_MIN_PLAUSIBLE <= val <= SPO2_MAX_PLAUSIBLE):
                    continue

                report.spo2.append(SpO2Reading(timestamp=dt, spo2_pct=val))
            except Exception as e:
                report.parse_errors.append(f"SPO2 row error: {e}")

        logger.info(f"SpO2: {len(report.spo2)} readings parsed")

    def _parse_stress(self, content: str, report: ZeppReport) -> None:
        """Parse STRESS.csv — stress score readings (0-100)."""
        header, rows = self._csv_rows(content)

        date_col = _find_column(header, ["date", "Date"])
        time_col = _find_column(header, ["time", "Time"])
        val_col = _find_column(
            header, ["stress", "stressScore", "stress_score", "value"]
        )

        if not val_col:
            report.parse_errors.append("STRESS: could not find stress value column")
            return

        for row in rows:
            try:
                raw_dt = f"{row.get(date_col, '')} {row.get(time_col, '')}".strip()
                dt = _parse_dt(raw_dt, self.DT_FORMATS)
                if not dt:
                    d = _parse_date(row.get(date_col, ""))
                    if d:
                        dt = datetime(d.year, d.month, d.day)
                    else:
                        continue

                val = _safe_int(row.get(val_col, "0"))
                if not (0 <= val <= 100):
                    continue

                report.stress.append(StressReading(timestamp=dt, stress_score=val))
            except Exception as e:
                report.parse_errors.append(f"STRESS row error: {e}")

        logger.info(f"Stress: {len(report.stress)} readings parsed")

    def _parse_weight(self, content: str, report: ZeppReport) -> None:
        """Parse BODY_WEIGHT.csv — weight and BMI entries."""
        header, rows = self._csv_rows(content)

        date_col = _find_column(header, ["date", "Date"])
        weight_col = _find_column(header, ["weight", "Weight", "weightKg", "weight_kg"])
        bmi_col = _find_column(header, ["bmi", "BMI"])

        if not weight_col:
            report.parse_errors.append("BODY_WEIGHT: could not find weight column")
            return

        for row in rows:
            try:
                d = _parse_date(row.get(date_col, "") if date_col else "")
                if not d:
                    continue

                weight = _safe_float(row.get(weight_col, ""))
                if weight is None or weight <= 0:
                    continue

                # Convert to kg if likely in grams or lbs
                if weight > 500:
                    weight = weight / 1000  # grams → kg
                elif weight > 150:
                    weight = weight * 0.453592  # lbs → kg (rough heuristic)

                bmi = _safe_float(row.get(bmi_col, "") if bmi_col else "")

                report.weight.append(
                    WeightEntry(
                        date=d,
                        weight_kg=round(weight, 2),
                        bmi=round(bmi, 1) if bmi else None,
                    )
                )
            except Exception as e:
                report.parse_errors.append(f"BODY_WEIGHT row error: {e}")

        logger.info(f"Weight: {len(report.weight)} entries parsed")


# ---------------------------------------------------------------------------
# CLI — python zepp_parser.py path/to/export.zip [--json]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python zepp_parser.py <path_to_zip_or_folder> [--json]")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    report = ZeppParser().parse(sys.argv[1])

    print("\n" + report.summary())

    if report.gaps:
        print(f"\n{'='*50}")
        print("DATA GAPS:")
        for g in report.gaps:
            print(f"  {g.start} → {g.end}  ({g.days} days)  [{g.reason}]")

    rhr = report.resting_hr_series()
    if rhr:
        print(f"\n{'='*50}")
        print("RESTING HR TREND (recent 10 data points):")
        for d, v in rhr[-10:]:
            print(f"  {d}   {v} bpm")

    if report.parse_errors:
        print(f"\nParse errors ({len(report.parse_errors)}):")
        for e in report.parse_errors[:10]:
            print(f"  {e}")

    if "--json" in sys.argv:
        print("\n--- JSON output ---")
        print(json.dumps(report.to_dict(), indent=2, default=str))
