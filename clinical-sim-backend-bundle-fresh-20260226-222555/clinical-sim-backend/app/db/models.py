"""SQLAlchemy ORM models for MedSim.

Schema: users, sessions, turns, events, scores, cases.
Works with SQLite locally, PostgreSQL (Supabase) in production.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    role = Column(
        Enum("learner", "faculty", "admin", name="user_role"),
        nullable=False,
        default="learner",
    )
    institution = Column(String(255), nullable=True)
    specialty = Column(String(100), nullable=True)
    training_level = Column(String(50), nullable=True)  # e.g. PGY-1, PGY-2, attending
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    case_id = Column(String(100), ForeignKey("cases.id"), nullable=True, index=True)
    status = Column(
        Enum("created", "active", "completed", "failed", "abandoned", name="session_status"),
        nullable=False,
        default="created",
    )
    difficulty = Column(String(20), default="moderate")
    patient_state = Column(JSON, nullable=True)
    case_definition = Column(JSON, nullable=True)
    device_mode = Column(String(20), default="local_demo")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), default=_utcnow)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="sessions")
    case = relationship("Case", back_populates="sessions")
    turns = relationship("Turn", back_populates="session", cascade="all, delete-orphan", order_by="Turn.sequence_index")
    events = relationship("Event", back_populates="session", cascade="all, delete-orphan", order_by="Event.sim_time_sec")
    score = relationship("Score", back_populates="session", uselist=False, cascade="all, delete-orphan")


class Turn(Base):
    __tablename__ = "turns"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    turn_id = Column(String(50), nullable=False)  # e.g. "turn-1"
    sequence_index = Column(Integer, nullable=False)
    sim_time_sec = Column(Float, nullable=False, default=0)
    raw_input = Column(Text, nullable=False)
    normalized_input = Column(Text, nullable=True)
    parser_mode = Column(String(30), nullable=False, default="rule")
    parsed_actions = Column(JSON, nullable=True)
    engine_result = Column(JSON, nullable=True)
    state_snapshot = Column(JSON, nullable=True)  # patient state after this turn
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    session = relationship("Session", back_populates="turns")


class Event(Base):
    __tablename__ = "events"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    event_id = Column(String(50), nullable=False)
    event_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="info")
    sim_time_sec = Column(Float, nullable=False, default=0)
    summary = Column(Text, nullable=True)
    structured_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    session = relationship("Session", back_populates="events")


class Score(Base):
    __tablename__ = "scores"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, unique=True)
    final_score = Column(Float, default=0)
    max_possible = Column(Float, default=100)
    critical_actions_completed = Column(JSON, default=list)
    critical_actions_missed = Column(JSON, default=list)
    harm_events_triggered = Column(JSON, default=list)
    teaching_points = Column(JSON, default=list)
    time_to_first_action_sec = Column(Float, nullable=True)
    total_sim_time_sec = Column(Float, nullable=True)
    grade = Column(String(2), nullable=True)  # A, B, C, D, F
    percentile = Column(Float, nullable=True)
    debrief_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    session = relationship("Session", back_populates="score")


class Case(Base):
    __tablename__ = "cases"

    id = Column(String(100), primary_key=True)
    title = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)  # e.g. "hypertensive_emergency", "septic_shock"
    difficulty = Column(String(20), default="moderate")
    scenario_type = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    teaching_focus = Column(JSON, nullable=True)  # list of strings
    case_data = Column(JSON, nullable=False)  # full case definition
    is_active = Column(Boolean, default=True)
    version = Column(String(20), default="2.0.0")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    sessions = relationship("Session", back_populates="case")


class InputLog(Base):
    """Persistent log of every user input for analysis and app improvement."""

    __tablename__ = "input_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), nullable=False, index=True)
    case_id = Column(String(100), nullable=True, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    turn_index = Column(Integer, nullable=False, default=0)
    turn_id = Column(String(50), nullable=True)
    sim_time_sec = Column(Float, nullable=False, default=0)
    raw_input = Column(Text, nullable=False)
    normalized_input = Column(Text, nullable=True)
    parser_mode = Column(String(30), nullable=True)
    action_count = Column(Integer, nullable=False, default=0)
    parsed_actions_summary = Column(Text, nullable=True)  # short summary of what was parsed
    had_parse_failure = Column(Boolean, default=False)  # True if parser returned 0 actions
    flagged = Column(Boolean, default=False, index=True)  # True if manually flagged for review
    flag_reason = Column(Text, nullable=True)  # why it was flagged
    flag_category = Column(String(50), nullable=True, index=True)  # bug, parser_fail, ux, content, other
    notes = Column(Text, nullable=True)  # developer notes
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Feedback(Base):
    """Developer/tester feedback entries linked to specific inputs or general issues."""

    __tablename__ = "feedback"

    id = Column(String(36), primary_key=True, default=_uuid)
    input_log_id = Column(String(36), ForeignKey("input_logs.id"), nullable=True, index=True)
    session_id = Column(String(100), nullable=True)
    category = Column(String(50), nullable=False, default="general")  # bug, parser_fail, ux, content, feature_request, other
    severity = Column(String(20), nullable=False, default="low")  # low, medium, high, critical
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="open")  # open, in_progress, resolved, wontfix
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
