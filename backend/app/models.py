"""SQLAlchemy persistence models for DEADLOOP."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes; API adds UTC marker)."""
    from datetime import timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    framework: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list[Session]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    events: Mapped[list[Event]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata_json", JSON, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="sessions")
    events: Mapped[list[Event]] = relationship(back_populates="session", cascade="all, delete-orphan")
    incidents: Mapped[list[Incident]] = relationship(back_populates="session")


Index("ix_sessions_agent_started", Session.agent_id, Session.started_at.desc())


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    normalized_input_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    semantic_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    task: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    parent_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata_json", JSON, nullable=True)
    progress: Mapped[dict[str, Any] | None] = mapped_column("progress_json", JSON, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sanitized_input: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    sanitized_output: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="events")
    session: Mapped[Session] = relationship(back_populates="events")


Index("ix_events_session_timestamp", Event.session_id, Event.timestamp)
Index("ix_events_agent_timestamp", Event.agent_id, Event.timestamp)
Index("ix_events_session_tool", Event.session_id, Event.tool_name)


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    ai_explanation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ai_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    incident: Mapped[Incident | None] = relationship(back_populates="detection", uselist=False)


Index("ix_detections_fingerprint", Detection.fingerprint, Detection.created_at.desc())
Index("ix_detections_session_created", Detection.session_id, Detection.created_at.desc())


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    detection_id: Mapped[str] = mapped_column(
        ForeignKey("detections.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    detection: Mapped[Detection] = relationship(back_populates="incident")
    agent: Mapped[Agent] = relationship()
    session: Mapped[Session] = relationship(back_populates="incidents")
    notes: Mapped[list[IncidentNote]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="IncidentNote.created_at"
    )
    interventions: Mapped[list[Intervention]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="Intervention.requested_at"
    )


Index("ix_incidents_status_created", Incident.status, Incident.created_at.desc())
Index("ix_incidents_severity_status", Incident.severity, Incident.status)


class IncidentNote(Base):
    __tablename__ = "incident_notes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author: Mapped[str] = mapped_column(String(100), nullable=False, default="admin")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="notes")


class Intervention(Base):
    __tablename__ = "interventions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_action: Mapped[str] = mapped_column(String(50), nullable=False)
    policy_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(30), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(30), nullable=False)
    initiated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="interventions")


Index("ix_interventions_incident_requested", Intervention.incident_id, Intervention.requested_at.desc())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


Index("ix_audit_resource_time", AuditLog.resource_type, AuditLog.resource_id, AuditLog.timestamp.desc())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


__all__ = [
    "Agent",
    "ApiKey",
    "AuditLog",
    "Detection",
    "Event",
    "Incident",
    "IncidentNote",
    "Intervention",
    "Session",
    "Setting",
    "utcnow",
]
