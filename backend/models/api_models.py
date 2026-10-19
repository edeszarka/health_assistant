from __future__ import annotations
from datetime import date, datetime
from typing import Literal, Optional, List
from pydantic import BaseModel, Field, model_validator


# ─── Lab Results ────────────────────────────────────────────────────────────


class LabResultResponse(BaseModel):
    """Single lab result returned by the API."""

    model_config = {"from_attributes": True}

    id: int
    test_name: str
    raw_name: str
    value: float
    unit: Optional[str]
    ref_range_low: Optional[float]
    ref_range_high: Optional[float]
    is_flagged: bool
    test_date: Optional[date]
    source_filename: Optional[str]
    created_at: datetime


class LabResultsListResponse(BaseModel):
    """Paginated list of lab results."""

    model_config = {"from_attributes": True}

    total: int
    items: List[LabResultResponse]


# ─── Blood Pressure ──────────────────────────────────────────────────────────


class BloodPressureCreate(BaseModel):
    """Payload for creating a new BP reading."""

    systolic: int
    diastolic: int
    pulse: Optional[int] = None
    context: Optional[str] = None  # morning/evening/after_exercise/stressed
    measured_at: Optional[datetime] = None


class BloodPressureResponse(BaseModel):
    """Single BP reading returned by the API."""

    model_config = {"from_attributes": True}

    id: int
    measured_at: datetime
    systolic: int
    diastolic: int
    pulse: Optional[int]
    context: Optional[str]
    classification: Optional[str] = None
    created_at: datetime


class BPSummaryResponse(BaseModel):
    """Aggregated blood pressure statistics."""

    avg_systolic_7d: Optional[float]
    avg_diastolic_7d: Optional[float]
    avg_systolic_30d: Optional[float]
    avg_diastolic_30d: Optional[float]
    classification: str
    trend_direction: str  # "improving" / "stable" / "worsening"
    reading_count: int


# ─── Family History ──────────────────────────────────────────────────────────


class FamilyHistoryCreate(BaseModel):
    """Payload for adding a family history entry."""

    relation: str
    condition: str
    icd10_code: Optional[str] = None
    age_of_onset: Optional[int] = None
    notes: Optional[str] = None


class MedlinePlusInfo(BaseModel):
    """A MedlinePlus summary and link for one code."""

    title: str
    summary: str
    url: str


class FamilyHistoryResponse(BaseModel):
    """Family history entry returned by the API.

    ``medlineplus`` is the cached MedlinePlus Connect text for the entry's
    ICD-10 code, or ``None`` when there is no code or nothing is cached.
    """

    model_config = {"from_attributes": True}

    id: int
    relation: str
    condition: str
    icd10_code: Optional[str]
    age_of_onset: Optional[int]
    notes: Optional[str]
    created_at: datetime
    medlineplus: Optional[MedlinePlusInfo] = None


# ─── Chat ────────────────────────────────────────────────────────────────────


# Where an assistant turn came from: the LLM, the app without the LLM (e.g.
# the stored-input list for a risk question), or a UI error message.
TurnSource = Literal["llm", "automatic", "error"]


class ChatTurn(BaseModel):
    """One earlier turn of the conversation.

    Only user and assistant turns are accepted, so a client cannot inject a
    system message that would override the server-side system prompt.
    ``source`` tells the backend which assistant turns the model did not write
    (see ``services.chat_history``); it defaults to ``"llm"``.
    """

    role: Literal["user", "assistant"]
    content: str
    source: TurnSource = "llm"


class ChatRequest(BaseModel):
    """User chat message + conversation history."""

    message: str
    conversation_history: List[ChatTurn] = []


class ChatResponse(BaseModel):
    """LLM reply with source citations.

    For an explicit risk-calculation request the reply is generated without
    the LLM and ``data_request`` carries the stored inputs, so the client can
    show the input form.
    """

    reply: str
    sources: List[str] = []
    language: str = "English"  # detected language of the user's message
    source: Literal["llm", "automatic"] = "llm"  # who wrote ``reply``
    data_request: Optional[RiskInputsStatus] = None


# ─── Dashboard ───────────────────────────────────────────────────────────────


class DashboardSummary(BaseModel):
    """Top-level health summary for the dashboard."""

    latest_labs: List[LabResultResponse]
    bp_summary: Optional[BPSummaryResponse]
    risk_scores: List[dict]
    active_flags: List[str]


# ─── Screening ───────────────────────────────────────────────────────────────


class ScreeningRecommendation(BaseModel):
    """A single preventive screening recommendation."""

    test_name: str
    reason: str
    urgency: str  # "routine" / "soon" / "urgent"
    specialist: str
    medlineplus_url: Optional[str] = None
    medlineplus_summary: Optional[str] = None


# ─── Risk Scores ─────────────────────────────────────────────────────────────


class RiskScoreResponse(BaseModel):
    """A calculated health risk score."""

    model_config = {"from_attributes": True}

    score_type: str
    score_value: float
    risk_category: str
    explanation: str


# ─── Risk inputs ─────────────────────────────────────────────────────────────

# Plausibility bounds for values typed into the risk form. They reject typos
# (e.g. 1800 cm, or mmol/L typed while mg/dL is selected), not unusual but
# real values. The mg/dL lower bounds match the risk engine's mmol/L guard
# (risk_engine.calculate_framingham), so an accepted value is always scorable.
HEIGHT_CM_RANGE = (100, 250)
WEIGHT_KG_RANGE = (25.0, 350.0)
WAIST_CM_RANGE = (40.0, 200.0)
CHOLESTEROL_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "total_cholesterol": {"mg/dL": (50.0, 600.0), "mmol/L": (1.3, 15.5)},
    "hdl_cholesterol": {"mg/dL": (10.0, 150.0), "mmol/L": (0.26, 3.9)},
}
EARLIEST_BIRTH_YEAR = 1900

FamilyDiabetes = Literal["none", "second_degree", "first_degree"]
InputStatus = Literal["ok", "stale", "missing", "unconvertible"]


class ProfileData(BaseModel):
    """The answers stored in ``user_profile``; all are required."""

    model_config = {"from_attributes": True}

    birth_year: int = Field(ge=EARLIEST_BIRTH_YEAR)
    birth_month: int = Field(ge=1, le=12)
    sex: Literal["male", "female"]
    height_cm: int = Field(ge=HEIGHT_CM_RANGE[0], le=HEIGHT_CM_RANGE[1])
    smoking: bool
    bp_medication_ever: bool
    bp_medication_current: bool
    high_glucose_history: bool
    diabetes_diagnosed: bool
    vegetables_daily: bool
    physically_active: bool
    family_diabetes: FamilyDiabetes

    @model_validator(mode="after")
    def _check_consistency(self) -> "ProfileData":
        """Reject answers that contradict each other or lie in the future."""
        today = date.today()
        if (self.birth_year, self.birth_month) > (today.year, today.month):
            raise ValueError("birth year and month cannot be in the future")
        if self.bp_medication_current and not self.bp_medication_ever:
            raise ValueError(
                "bp_medication_current implies bp_medication_ever"
            )
        if self.diabetes_diagnosed and not self.high_glucose_history:
            raise ValueError(
                "diabetes_diagnosed implies high_glucose_history"
            )
        return self


class ManualLabValue(BaseModel):
    """A cholesterol value typed into the risk form, with an explicit unit."""

    value: float
    unit: Literal["mg/dL", "mmol/L"]
    test_date: date

    @model_validator(mode="after")
    def _check_date(self) -> "ManualLabValue":
        """Reject a test date in the future."""
        if self.test_date > date.today():
            raise ValueError("test_date cannot be in the future")
        return self


class RiskInputsUpdate(BaseModel):
    """Payload of the risk form: the profile plus optional fresh measurements.

    A measurement left out keeps the stored one.
    """

    profile: ProfileData
    weight_kg: Optional[float] = Field(
        default=None, ge=WEIGHT_KG_RANGE[0], le=WEIGHT_KG_RANGE[1]
    )
    waist_cm: Optional[float] = Field(
        default=None, ge=WAIST_CM_RANGE[0], le=WAIST_CM_RANGE[1]
    )
    total_cholesterol: Optional[ManualLabValue] = None
    hdl_cholesterol: Optional[ManualLabValue] = None

    @model_validator(mode="after")
    def _check_lab_ranges(self) -> "RiskInputsUpdate":
        """Reject cholesterol values outside the plausible range for their unit."""
        for name in ("total_cholesterol", "hdl_cholesterol"):
            lab = getattr(self, name)
            if lab is None:
                continue
            low, high = CHOLESTEROL_RANGES[name][lab.unit]
            if not low <= lab.value <= high:
                raise ValueError(
                    f"{name} must be between {low} and {high} {lab.unit}"
                )
        return self


class StoredInput(BaseModel):
    """The latest stored value of one measured risk input."""

    value: Optional[float] = None
    unit: Optional[str] = None
    recorded_on: Optional[date] = None
    status: InputStatus = "missing"


class RiskInputsStatus(BaseModel):
    """What is stored for each risk input, and what each score still needs."""

    profile: Optional[ProfileData] = None
    age: Optional[int] = None
    weight_kg: StoredInput
    waist_cm: StoredInput
    systolic_bp: StoredInput
    total_cholesterol: StoredInput
    hdl_cholesterol: StoredInput
    findrisc_missing: List[str]
    framingham_missing: List[str]
    framingham_unavailable: Optional[str] = None


class RiskCalculationResponse(BaseModel):
    """Baseline scores computed (and persisted) from the stored inputs."""

    findrisc_score: Optional[int] = None
    findrisc_category: Optional[str] = None
    framingham_risk_percent: Optional[float] = None
    framingham_category: Optional[str] = None
    inputs: RiskInputsStatus


# ChatResponse refers to RiskInputsStatus, which is defined further down.
ChatResponse.model_rebuild()
