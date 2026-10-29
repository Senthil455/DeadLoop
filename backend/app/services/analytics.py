"""Database-backed dashboard metrics and time series."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from ..database import engine
from ..models import Agent, Detection, Event, Incident, Intervention, Session, utcnow
from .serializers import agent_to_dict, incident_to_dict

OPEN_STATUSES = ("OPEN", "ACKNOWLEDGED")


def _hour_key(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00Z")


def event_series(db: DbSession, hours: int = 24) -> list[dict[str, Any]]:
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=hours - 1)
    if engine.dialect.name == "postgresql":
        bucket = func.date_trunc("hour", Event.timestamp)
    else:
        bucket = func.strftime("%Y-%m-%dT%H:00:00", Event.timestamp)
    rows = db.execute(
        select(bucket.label("bucket"), func.count(Event.id))
        .where(Event.timestamp >= start)
        .group_by("bucket")
    ).all()
    counts: dict[str, int] = {}
    for raw_bucket, count in rows:
        if isinstance(raw_bucket, str):
            key = raw_bucket if raw_bucket.endswith("Z") else raw_bucket + "Z"
        else:
            key = _hour_key(raw_bucket)
        counts[key] = int(count)
    series = []
    for offset in range(hours):
        moment = start + timedelta(hours=offset)
        key = moment.strftime("%Y-%m-%dT%H:00:00Z")
        series.append({"bucket": key, "events": counts.get(key, 0)})
    return series


def build_overview(db: DbSession) -> dict[str, Any]:
    total_agents = db.scalar(select(func.count(Agent.id))) or 0
    active_sessions = (
        db.scalar(select(func.count(Session.id)).where(Session.status == "active")) or 0
    )
    open_incidents = (
        db.scalar(
            select(func.count(Incident.id)).where(Incident.status.in_(OPEN_STATUSES))
        )
        or 0
    )
    high_severity = (
        db.scalar(
            select(func.count(Incident.id)).where(
                Incident.status.in_(OPEN_STATUSES),
                Incident.severity.in_(["HIGH", "CRITICAL"]),
            )
        )
        or 0
    )
    repetition = (
        db.scalar(
            select(func.count(Detection.id)).where(
                Detection.category.in_(["exact_repetition", "semantic_repetition"])
            )
        )
        or 0
    )
    failed_calls = (
        db.scalar(select(func.count(Event.id)).where(Event.status == "failure")) or 0
    )
    recent_interventions = db.execute(
        select(Intervention).order_by(Intervention.requested_at.desc()).limit(5)
    ).scalars().all()
    recent_agents = db.execute(
        select(Agent).order_by(Agent.last_seen_at.desc().nullslast()).limit(8)
    ).scalars().all()
    incidents = db.execute(
        select(Incident).order_by(Incident.created_at.desc()).limit(8)
    ).scalars().all()
    demo_mode = bool(db.scalar(select(func.count(Agent.id)).where(Agent.is_demo.is_(True))))

    return {
        "total_agents": total_agents,
        "active_sessions": active_sessions,
        "open_incidents": open_incidents,
        "high_severity_incidents": high_severity,
        "repetition_detections": repetition,
        "failed_tool_calls": failed_calls,
        "recent_interventions": recent_interventions,
        "recent_activity": [agent_to_dict(db, agent) for agent in recent_agents],
        "incident_feed": [incident_to_dict(db, incident) for incident in incidents],
        "event_series": event_series(db),
        "demo_mode": demo_mode,
        "generated_at": utcnow().isoformat() + "Z",
    }


__all__ = ["build_overview", "event_series"]
