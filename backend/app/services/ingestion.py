"""Event ingestion, idempotency, and automatic detection."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from ..core.fingerprint import canonical_json, fingerprint
from ..core.redaction import RedactionPolicy, sanitize, truncate_text
from ..detection.engine import analyze_session
from ..models import Agent, Event, Session, utcnow
from ..schemas import EventIn
from ..services.settings import get_general_settings


def _progress_payload(payload: EventIn) -> dict[str, Any] | None:
    if payload.progress is None:
        return None
    if hasattr(payload.progress, "model_dump"):
        return payload.progress.model_dump(exclude_none=True)
    return dict(payload.progress)


def _sanitized_text(value: str | None, policy: RedactionPolicy) -> str | None:
    if value is None:
        return None
    result = sanitize(value, policy)
    return truncate_text(str(result), 1000)


def _ensure_agent(db: DbSession, agent_id: str, timestamp) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        agent = Agent(
            id=agent_id,
            name=agent_id,
            status="active",
            is_demo=False,
            created_at=utcnow(),
            last_seen_at=timestamp,
        )
        db.add(agent)
        db.flush()
    elif agent.last_seen_at is None or timestamp > agent.last_seen_at:
        agent.last_seen_at = timestamp
    if agent.status == "unknown":
        agent.status = "active"
    return agent


def _ensure_session(db: DbSession, session_id: str, agent_id: str, timestamp) -> Session:
    session = db.get(Session, session_id)
    if session is None:
        session = Session(
            id=session_id,
            agent_id=agent_id,
            status="active",
            started_at=timestamp,
            meta={},
            event_count=0,
        )
        db.add(session)
        db.flush()
    else:
        if session.agent_id != agent_id:
            raise ValueError(
                f"session_id '{session_id}' belongs to a different agent; use a unique session id."
            )
        if timestamp < session.started_at:
            session.started_at = timestamp
    return session


def build_event_row(payload: EventIn, policy: RedactionPolicy) -> Event:
    timestamp = payload.timestamp or utcnow()
    sanitized_input = sanitize(payload.input, policy)
    sanitized_output = sanitize(payload.output, policy)
    metadata = sanitize(payload.metadata, policy) if payload.metadata is not None else None
    progress = _progress_payload(payload)
    normalized = fingerprint(sanitized_input)
    semantic = hashlib.sha256(
        canonical_json(sanitized_input, lowercase=True).encode("utf-8")
    ).hexdigest()
    return Event(
        id=payload.event_id or secrets.token_hex(16),
        agent_id=payload.agent_id.strip(),
        session_id=payload.session_id.strip(),
        timestamp=timestamp,
        received_at=utcnow(),
        tool_name=payload.tool_name,
        action=payload.action,
        normalized_input_hash=normalized,
        semantic_hash=semantic,
        status=payload.status,
        duration_ms=payload.duration_ms,
        error_category=payload.error_category,
        retry_count=payload.retry_count,
        tokens=payload.tokens,
        cost_usd=payload.cost_usd,
        task=_sanitized_text(payload.task, policy),
        parent_event_id=payload.parent_event_id,
        correlation_id=payload.correlation_id,
        meta=metadata,
        progress=progress,
        model_id=payload.model,
        sanitized_input=sanitized_input,
        sanitized_output=sanitized_output,
    )


def ingest_payloads(db: DbSession, payloads: list[EventIn]) -> dict[str, Any]:
    """Ingest validated events. Assumes the caller commits the transaction."""
    general = get_general_settings(db)
    policy = RedactionPolicy(
        enabled=general.redaction_enabled, extra_keys=general.redaction_keys
    )
    accepted = 0
    duplicates = 0
    rejected: list[dict[str, Any]] = []
    touched_sessions: dict[str, tuple[str, Session]] = {}

    for index, payload in enumerate(payloads):
        try:
            with db.begin_nested():
                event = build_event_row(payload, policy)
                existing = db.get(Event, event.id)
                if existing is not None:
                    duplicates += 1
                    continue
                _ensure_agent(db, event.agent_id, event.timestamp)
                session = _ensure_session(db, event.session_id, event.agent_id, event.timestamp)
                db.add(event)
                db.flush()
                session.event_count = (session.event_count or 0) + 1
                touched_sessions[event.session_id] = (event.agent_id, session)
            accepted += 1
        except ValueError as exc:
            rejected.append({"index": index, "error": str(exc)})
        except IntegrityError as exc:
            rejected.append(
                {
                    "index": index,
                    "error": "Event conflicted with an existing record.",
                    "detail": str(exc.orig) if exc.orig else None,
                }
            )

    detections_created = 0
    incidents_created = 0
    for agent_id, session in touched_sessions.values():
        agent = db.get(Agent, agent_id)
        created, incidents = analyze_session(
            db, session, agent.configuration if agent else None
        )
        detections_created += created
        incidents_created += incidents

    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": rejected,
        "detections_created": detections_created,
        "incidents_created": incidents_created,
        "session_ids": sorted(touched_sessions.keys()),
    }


__all__ = ["build_event_row", "ingest_payloads"]
