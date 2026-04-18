import datetime
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
)
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from database.connection import Base


class UserProfile(Base):
    """Stores the single user's demographic and risk-factor profile."""

    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, index=True)
    age = Column(Integer, nullable=False)
    sex = Column(String(10), nullable=False)  # "male" / "female" / "other"
    height_cm = Column(Integer, nullable=True)
    waist_cm = Column(Integer, nullable=True)
    smoking = Column(Boolean, default=False)
    bp_medication = Column(Boolean, default=False)
    high_glucose_history = Column(Boolean, default=False)
    vegetables_daily = Column(Boolean, default=False)
    family_diabetes = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
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
    # steps / sleep_minutes / heart_rate / weight_kg / bmi
    value = Column(Float, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    source_file = Column(String(256))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


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
