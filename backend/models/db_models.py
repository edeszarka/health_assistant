import datetime
from typing import cast
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Date,
    Text,
    DateTime,
    ForeignKey,
    func,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from database.connection import Base


def age_on(birth_year: int, birth_month: int, today: datetime.date) -> int:
    """Return the age in whole years from a birth year and month.

    The birthday is taken as the first day of the birth month, so the result
    is at most one month early; only year and month are stored.

    Args:
        birth_year: Year of birth.
        birth_month: Month of birth, 1-12.
        today: The reference date.

    Returns:
        The age in completed years.
    """
    had_birthday = today.month >= birth_month
    return today.year - birth_year - (0 if had_birthday else 1)


class UserProfile(Base):
    """Stores the single user's demographic and risk-factor profile.

    Weight and waist circumference change over time, so they are stored as
    measurements in ``samsung_health_metrics`` (``weight_kg``, ``waist_cm``),
    not here. Every column is answered on the profile form, so a stored row is
    always complete.
    """

    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, index=True)
    birth_year = Column(Integer, nullable=False)
    birth_month = Column(Integer, nullable=False)
    sex = Column(String(10), nullable=False)  # biological sex: "male" / "female"
    height_cm = Column(Integer, nullable=False)
    smoking = Column(Boolean, nullable=False, default=False)
    # FINDRISC asks whether BP medication was EVER taken regularly; Framingham
    # asks whether BP is CURRENTLY treated.
    bp_medication_ever = Column(Boolean, nullable=False, default=False)
    bp_medication_current = Column(Boolean, nullable=False, default=False)
    # FINDRISC: high blood glucose ever found; Framingham: diagnosed diabetes.
    high_glucose_history = Column(Boolean, nullable=False, default=False)
    diabetes_diagnosed = Column(Boolean, nullable=False, default=False)
    vegetables_daily = Column(Boolean, nullable=False, default=False)
    # FINDRISC: at least 30 minutes of physical activity daily.
    physically_active = Column(Boolean, nullable=False, default=False)
    # FINDRISC: "none" / "second_degree" / "first_degree"
    family_diabetes = Column(String(16), nullable=False, default="none")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def age(self) -> int:
        """Age in whole years today, derived from birth year and month."""
        return age_on(
            cast(int, self.birth_year), cast(int, self.birth_month), datetime.date.today()
        )


class LabResult(Base):
    """Parsed and normalised laboratory test results."""

    __tablename__ = "lab_results"

    id = Column(Integer, primary_key=True, index=True)
    test_name = Column(String(128), nullable=False, index=True)  # normalised key
    raw_name = Column(String(256), nullable=False)  # original from PDF
    value = Column(Float, nullable=False)
    unit = Column(String(64))
    ref_range_low = Column(Float, nullable=True)
    ref_range_high = Column(Float, nullable=True)
    is_flagged = Column(Boolean, default=False)
    test_date = Column(Date, nullable=True)
    source_filename = Column(String(256))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BloodPressureReading(Base):
    """Individual blood pressure measurements."""

    __tablename__ = "blood_pressure_readings"

    id = Column(Integer, primary_key=True, index=True)
    measured_at = Column(DateTime(timezone=True), nullable=False)
    systolic = Column(Integer, nullable=False)
    diastolic = Column(Integer, nullable=False)
    pulse = Column(Integer, nullable=True)
    context = Column(
        String(32), nullable=True
    )  # morning/evening/after_exercise/stressed
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FamilyHistory(Base):
    """Family medical history entries."""

    __tablename__ = "family_history"

    id = Column(Integer, primary_key=True, index=True)
    relation = Column(
        String(64), nullable=False
    )  # mother/father/maternal_grandmother …
    condition = Column(String(256), nullable=False)
    icd10_code = Column(String(16), nullable=True)
    age_of_onset = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SamsungHealthMetric(Base):
    """Metrics imported from Samsung Health ZIP exports."""

    __tablename__ = "samsung_health_metrics"

    id = Column(Integer, primary_key=True, index=True)
    metric_type = Column(String(32), nullable=False, index=True)
    # steps / sleep_minutes / heart_rate / weight_kg / bmi / waist_cm
    # Manual entries (weight_kg, waist_cm from the risk form) use a
    # "manual_<timestamp>_<uuid>" source_file.
    value = Column(Float, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    source_file = Column(String(256))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("metric_type", "recorded_at", name="uix_metric_type_recorded_at"),
    )


class Embedding(Base):
    """pgvector embeddings for RAG."""

    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    # lab_result / samsung_summary / family_history / guideline / bp_summary
    source_id = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MedlinePlusCache(Base):
    """Cache for MedlinePlus API responses."""

    __tablename__ = "medlineplus_cache"

    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String(256), unique=True, nullable=False, index=True)
    query_term = Column(String(256), nullable=False)
    response_json = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RiskScore(Base):
    """Stored risk score calculations."""

    __tablename__ = "risk_scores"

    id = Column(Integer, primary_key=True, index=True)
    score_type = Column(String(32), nullable=False, index=True)
    # framingham / findrisc / bp_classification
    score_value = Column(Float, nullable=False)
    risk_category = Column(String(64), nullable=False)
    inputs_json = Column(Text, nullable=False)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now())
