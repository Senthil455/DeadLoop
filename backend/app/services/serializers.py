"""Serialization helpers that enrich persisted records for the API."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from ..models import (
    Agent,
    AuditLog,
    Detection,
    Incident,
    IncidentNote,
    Intervention,
    Session,
    utcnow,
)


def agent_health(agent: Agent, open_incidents: int, now=None) -> str:
    now = now or utcnow()
    if agent.last_seen_at is None:
        return "unknown"
    age = now - agent.last_seen_at
    if open_incidents > 0:
        return "degraded"
    if age <= timedelta(minutes=15):
        return "active"
    if age <= timedelta(hours=24):
        return "stale"
    return "offline"


def agent_to_dict(db: DbSession, agent: Agent) -> dict[str, Any]:
    session_count = db.scalar(
        select(func.count(Session.id)).where(Session.agent_id == agent.id)
    ) or 0
    open_incidents = (
        db.scalar(
            select(func.count(Incident.id)).where(
                Incident.agent_id == agent.id,
                Incident.status.in_(["OPEN", "ACKNOWLEDGED"]),
            )
        )
        or 0
    )
    last_session = db.execute(
        select(Session)
        .where(Session.agent_id == agent.id)
        .order_by(Session.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "framework": agent.framework,
        "status": agent_health(agent, open_incidents),
        "is_demo": agent.is_demo,
        "configuration": agent.configuration,
        "created_at": agent.created_at,
        "last_seen_at": agent.last_seen_at,
        "session_count": session_count,
        "event_count": db.scalar(
            select(func.coalesce(func.sum(Session.event_count), 0)).where(
                Session.agent_id == agent.id
            )
        )
        or 0,
        "open_incidents": open_incidents,
        "last_session_id": last_session.id if last_session else None,
    }


def incident_to_dict(
    db: DbSession,
    incident: Incident,
    *,
    include_detail: bool = False,
) -> dict[str, Any]:
    detection = incident.detection
    agent_name = incident.agent.name if incident.agent else None
    data: dict[str, Any] = {
        "id": incident.id,
        "title": incident.title,
        "status": incident.status,
        "severity": incident.severity,
        "risk_score": incident.risk_score,
        "agent_id": incident.agent_id,
        "session_id": incident.session_id,
        "agent_name": agent_name,
        "detection_id": incident.detection_id,
        "detection_category": detection.category if detection else None,
        "confidence": detection.confidence if detection else None,
        "created_at": incident.created_at,
        "updated_at": incident.updated_at,
        "resolved_at": incident.resolved_at,
        "evidence_event_count": len((detection.evidence or {}).get("event_ids", []))
        if detection
        else 0,
        "evidence_event_ids": (detection.evidence or {}).get("event_ids", [])
        if detection
        else [],
    }
    if include_detail:
        data["detection"] = detection
        data["notes"] = incident.notes
        data["interventions"] = incident.interventions
        data["audit"] = db.execute(
            select(AuditLog)
            .where(
                AuditLog.resource_type == "incident",
                AuditLog.resource_id == incident.id,
            )
            .order_by(AuditLog.timestamp.desc())
            .limit(50)
        ).scalars().all()
    return data


def session_to_dict(
    db: DbSession, session: Session, *, agent_name: str | None = None
) -> dict[str, Any]:
    open_incidents = (
        db.scalar(
            select(func.count(Incident.id)).where(
                Incident.session_id == session.id,
                Incident.status.in_(["OPEN", "ACKNOWLEDGED"]),
            )
        )
        or 0
    )
    return {
        "id": session.id,
        "agent_id": session.agent_id,
        "status": session.status,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "event_count": session.event_count,
        "metadata": session.meta,
        "agent_name": agent_name,
        "open_incidents": open_incidents,
    }


def audit(db: DbSession, actor: str, action: str, resource_type: str, resource_id: str, details: dict[str, Any] | None = None) -> AuditLog:
    from ..core.redaction import sanitize

    entry = AuditLog(
        id=__import__("secrets").token_hex(16),
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=sanitize(details) if details else None,
    )
    db.add(entry)
    db.flush()
    return entry


def json_safe(value: Any) -> Any:
    """Best-effort conversion for evidence previews."""
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


__all__ = [
    "agent_health",
    "agent_to_dict",
    "audit",
    "incident_to_dict",
    "json_safe",
    "session_to_dict",
]
