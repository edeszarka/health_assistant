from __future__ import annotations
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


# ─── Lab Results ────────────────────────────────────────────────────────────

class LabResultResponse(BaseModel):
    """Single lab result returned by the API."""

    model_config = ConfigDict(from_attributes=True)

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
    context: Optional[str] = None   # morning/evening/after_exercise/stressed
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
    trend_direction: str   # "improving" / "stable" / "worsening"
    reading_count: int


# ─── Family History ──────────────────────────────────────────────────────────

class FamilyHistoryCreate(BaseModel):
    """Payload for adding a family history entry."""

    relation: str
    condition: str
    icd10_code: Optional[str] = None
    age_of_onset: Optional[int] = None
    notes: Optional[str] = None


class FamilyHistoryResponse(BaseModel):
    """Family history entry returned by the API."""

    model_config = {"from_attributes": True}

    id: int
    relation: str
    condition: str
    icd10_code: Optional[str]
    age_of_onset: Optional[int]
    notes: Optional[str]
    created_at: datetime


# ─── Chat ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """User chat message + conversation history."""

    message: str
    conversation_history: List[dict] = []
    query_type: str = "general"


class ChatResponse(BaseModel):
    """LLM reply with source citations."""

    reply: str
    sources: List[str] = []


# ─── Dashboard ───────────────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    """Top-level health summary for the dashboard."""

    latest_labs: List[LabResultResponse]
    bp_summary: Optional[BPSummaryResponse]
    risk_scores: List[dict]
    active_flags: List[str]
    recommendations_count: int


# ─── Screening ───────────────────────────────────────────────────────────────

class ScreeningRecommendation(BaseModel):
    """A single preventive screening recommendation."""

    test_name: str
    reason: str
    urgency: str   # "routine" / "soon" / "urgent"
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
