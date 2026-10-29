"""Pydantic request/response schemas and UTC serialization."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_serializer

from .core.redaction import truncate_text
from .services.settings import GeneralSettings


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# Response timestamps are always timezone-aware so browsers never reinterpret a
# naive datetime as local time.
UTCDateTime = Annotated[datetime, AfterValidator(_ensure_utc)]


def to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_serializer(mode="wrap")
    def _serialize_datetimes(self, handler):
        data = handler(self)

        def convert(item: Any) -> Any:
            if isinstance(item, datetime):
                return utc_iso(item)
            if isinstance(item, dict):
                return {k: convert(v) for k, v in item.items()}
            if isinstance(item, list):
                return [convert(v) for v in item]
            return item

        return convert(data)


EventStatus = Literal["success", "failure", "unknown"]
IncidentStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"]


class ProgressInput(BaseModel):
    made_progress: bool | None = None
    note: str | None = Field(None, max_length=500)
    checkpoint: str | None = Field(None, max_length=200)


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str | None = Field(None, min_length=1, max_length=128)
    agent_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=1, max_length=128)
    timestamp: datetime | None = None
    tool_name: str = Field(..., min_length=1, max_length=200)
    action: str | None = Field(None, max_length=200)
    input: Any = None
    output: Any = None
    status: EventStatus = "unknown"
    error_category: str | None = Field(None, max_length=200)
    duration_ms: int | None = Field(None, ge=0, le=86_400_000)
    retry_count: int = Field(0, ge=0, le=1000)
    tokens: int | None = Field(None, ge=0, le=100_000_000)
    cost_usd: float | None = Field(None, ge=0, le=1_000_000)
    task: str | None = Field(None, max_length=1000)
    parent_event_id: str | None = Field(None, max_length=128)
    correlation_id: str | None = Field(None, max_length=128)
    metadata: dict[str, Any] | None = None
    progress: ProgressInput | dict[str, Any] | None = None
    model: str | None = Field(None, max_length=200)

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"ok", "succeeded", "completed"}:
                return "success"
            if normalized in {"error", "failed", "errored"}:
                return "failure"
            return normalized
        return value

    @field_validator("timestamp")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        return to_naive_utc(value) if value else None

    @field_validator("tool_name", "agent_id", "session_id")
    @classmethod
    def _strip_identifiers(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("action", "error_category", "task", "model")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class EventBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[EventIn] = Field(..., min_length=1, max_length=100)

    @field_validator("events")
    @classmethod
    def _unique_event_ids(cls, events: list[EventIn]) -> list[EventIn]:
        seen: set[str] = set()
        for event in events:
            if event.event_id:
                if event.event_id in seen:
                    raise ValueError(f"duplicate event_id in batch: {event.event_id}")
                seen.add(event.event_id)
        return events


class EventOut(APIModel):
    id: str
    agent_id: str
    session_id: str
    timestamp: UTCDateTime
    received_at: UTCDateTime
    tool_name: str
    action: str | None
    status: str
    duration_ms: int | None
    error_category: str | None
    retry_count: int
    tokens: int | None
    cost_usd: float | None
    task: str | None
    parent_event_id: str | None
    correlation_id: str | None
    metadata: dict[str, Any] | None = Field(None, validation_alias="meta")
    progress: dict[str, Any] | None = Field(None, validation_alias="progress")
    model_id: str | None
    normalized_input_hash: str
    sanitized_input: Any = None
    sanitized_output: Any = None


class SessionOut(APIModel):
    id: str
    agent_id: str
    status: str
    started_at: UTCDateTime
    ended_at: UTCDateTime | None
    event_count: int
    metadata: dict[str, Any] | None = Field(None, validation_alias="meta")
    agent_name: str | None = None
    open_incidents: int = 0


class DetectionOut(APIModel):
    id: str
    agent_id: str
    session_id: str
    category: str
    severity: str
    risk_score: int
    confidence: float
    evidence: dict[str, Any]
    explanation: str
    recommended_action: str
    first_seen_at: UTCDateTime
    last_seen_at: UTCDateTime
    created_at: UTCDateTime
    updated_at: UTCDateTime
    ai_explanation: dict[str, Any] | None = None
    ai_generated_at: UTCDateTime | None = None


class IncidentNoteOut(APIModel):
    id: str
    author: str
    body: str
    created_at: UTCDateTime


class InterventionOut(APIModel):
    id: str
    incident_id: str
    agent_id: str
    session_id: str
    requested_action: str
    policy_mode: str
    approval_status: str
    execution_status: str
    initiated_by: str
    requested_at: UTCDateTime
    completed_at: UTCDateTime | None
    simulated: bool
    result: dict[str, Any] | None


class AuditOut(APIModel):
    id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    timestamp: UTCDateTime
    details: dict[str, Any] | None


class IncidentOut(APIModel):
    id: str
    title: str
    status: str
    severity: str
    risk_score: int
    agent_id: str
    session_id: str
    agent_name: str | None = None
    detection_id: str
    detection_category: str | None = None
    confidence: float | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    resolved_at: UTCDateTime | None
    evidence_event_count: int = 0
    evidence_event_ids: list[str] = Field(default_factory=list)


class IncidentDetail(IncidentOut):
    detection: DetectionOut
    notes: list[IncidentNoteOut] = Field(default_factory=list)
    interventions: list[InterventionOut] = Field(default_factory=list)
    audit: list[AuditOut] = Field(default_factory=list)


class AgentOut(APIModel):
    id: str
    name: str
    description: str | None
    framework: str | None
    status: str
    is_demo: bool
    configuration: dict[str, Any] | None
    created_at: UTCDateTime
    last_seen_at: UTCDateTime | None
    session_count: int = 0
    event_count: int = 0
    open_incidents: int = 0
    last_session_id: str | None = None


class SessionDetailOut(SessionOut):
    events: list[EventOut] = Field(default_factory=list)
    incidents: list[IncidentOut] = Field(default_factory=list)
    total_events: int = 0
    page: int = 1
    page_size: int = 50
    pages: int = 1
    tools: list[str] = Field(default_factory=list)


class IngestResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    detections_created: int = 0
    incidents_created: int = 0
    session_ids: list[str] = Field(default_factory=list)


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    framework: str | None = Field(None, max_length=100)
    configuration: dict[str, Any] | None = None

    @field_validator("name", "framework")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(..., min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _clean(cls, value: str) -> str:
        return truncate_text(value.strip(), 2000)


class IncidentStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: IncidentStatus
    note: str | None = Field(None, max_length=2000)


class InterventionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause"] = "pause"


class InterventionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(None, max_length=1000)


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        return value.strip()


class ApiKeyOut(APIModel):
    id: str
    name: str
    prefix: str
    created_at: UTCDateTime
    last_used_at: UTCDateTime | None
    revoked_at: UTCDateTime | None


class ApiKeyCreated(ApiKeyOut):
    api_key: str
    note: str = "This key is shown once. Store it securely."


class GeneralSettingsOut(GeneralSettings):
    ai_api_key_configured: bool = False
    ai_active: bool = False
    ai_provider: str = "openai-compatible"
    ai_config_source: str = "environment"


class GeneralSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retention_days: int | None = Field(None, ge=1, le=365)
    redaction_enabled: bool | None = None
    redaction_keys: list[str] | None = None
    intervention_mode: str | None = None
    ai_enabled: bool | None = None
    ai_base_url: str | None = None
    ai_model: str | None = None


class HealthOut(BaseModel):
    status: str
    database: str
    version: str
    environment: str
    ai_enabled: bool
    intervention_mode: str
    demo_mode: bool
    time: str


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False


class DemoScenarioResult(BaseModel):
    scenario: str
    agent_id: str
    session_id: str
    events_created: int
    detections_created: int
    incident_ids: list[str]
    detections: list[str]
    note: str


class StatsOverview(BaseModel):
    total_agents: int
    active_sessions: int
    open_incidents: int
    high_severity_incidents: int
    repetition_detections: int
    failed_tool_calls: int
    recent_interventions: list[InterventionOut]
    recent_activity: list[AgentOut]
    incident_feed: list[IncidentOut]
    event_series: list[dict[str, Any]]
    demo_mode: bool
    generated_at: str


__all__ = [
    "AgentOut",
    "AgentPatch",
    "ApiKeyCreate",
    "ApiKeyCreated",
    "ApiKeyOut",
    "AuditOut",
    "DemoRequest",
    "DemoScenarioResult",
    "DetectionOut",
    "EventBatchIn",
    "EventIn",
    "EventOut",
    "GeneralSettingsOut",
    "GeneralSettingsUpdate",
    "HealthOut",
    "IncidentDetail",
    "IncidentNoteOut",
    "IncidentOut",
    "IncidentStatusUpdate",
    "IngestResult",
    "InterventionDecision",
    "InterventionOut",
    "InterventionRequest",
    "NoteCreate",
    "SessionDetailOut",
    "SessionOut",
    "StatsOverview",
]
