"""Agent and session read APIs."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from ..core.security import require_admin
from ..database import get_db
from ..models import Agent, Detection, Event, Incident, Session
from ..schemas import AgentOut, AgentPatch, EventOut, SessionDetailOut, SessionOut
from ..services.serializers import audit, agent_to_dict, incident_to_dict, session_to_dict

router = APIRouter(prefix="/api/v1", tags=["agents"])


@router.get("/agents", response_model=list[AgentOut])
def list_agents(
    db: DbSession = Depends(get_db), _: str = Depends(require_admin)
):
    agents = db.execute(
        select(Agent).order_by(Agent.last_seen_at.desc().nullslast(), Agent.created_at.desc())
    ).scalars().all()
    return [agent_to_dict(db, agent) for agent in agents]


@router.get("/agents/{agent_id}", response_model=AgentOut)
def get_agent(
    agent_id: str, db: DbSession = Depends(get_db), _: str = Depends(require_admin)
):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent_to_dict(db, agent)


@router.patch("/agents/{agent_id}", response_model=AgentOut)
def patch_agent(
    agent_id: str,
    payload: AgentPatch,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"]:
        agent.name = changes["name"]
    if "description" in changes:
        agent.description = changes["description"]
    if "framework" in changes:
        agent.framework = changes["framework"]
    if "configuration" in changes:
        configuration = changes["configuration"] or {}
        if "detection" in configuration:
            from ..services.settings import DetectionSettings

            try:
                DetectionSettings.model_validate(
                    DetectionSettings().merged_with(configuration["detection"]).model_dump()
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail=f"Invalid per-agent detection configuration: {exc}"
                ) from exc
        agent.configuration = configuration
    audit(
        db,
        "admin",
        "agent.updated",
        "agent",
        agent.id,
        {"fields": sorted(changes.keys())},
    )
    db.commit()
    db.refresh(agent)
    return agent_to_dict(db, agent)


def _session_events(
    db: DbSession,
    session: Session,
    *,
    tool: str | None,
    status_filter: str | None,
    search: str | None,
    category: str | None,
    start: datetime | None,
    end: datetime | None,
    order: Literal["asc", "desc"],
    page: int,
    page_size: int,
):
    query = select(Event).where(Event.session_id == session.id)
    if tool:
        query = query.where(Event.tool_name == tool)
    if status_filter:
        query = query.where(Event.status == status_filter)
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(
            or_(
                Event.tool_name.ilike(pattern),
                Event.action.ilike(pattern),
                Event.error_category.ilike(pattern),
                Event.task.ilike(pattern),
            )
        )
    if start:
        query = query.where(Event.timestamp >= start)
    if end:
        query = query.where(Event.timestamp <= end)
    if category:
        detections = db.execute(
            select(Detection).where(
                Detection.session_id == session.id, Detection.category == category
            )
        ).scalars().all()
        event_ids: set[str] = set()
        for detection in detections:
            evidence = detection.evidence or {}
            event_ids.update(str(eid) for eid in evidence.get("event_ids", []))
        if not event_ids:
            return [], 0
        query = query.where(Event.id.in_(event_ids))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    ordering = Event.timestamp.asc() if order == "asc" else Event.timestamp.desc()
    events = db.execute(
        query.order_by(ordering, Event.id).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return events, total


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    agent_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    query = select(Session).order_by(Session.started_at.desc()).limit(limit)
    if agent_id:
        query = query.where(Session.agent_id == agent_id)
    if status_filter:
        query = query.where(Session.status == status_filter)
    sessions = db.execute(query).scalars().all()
    agent_names = {
        agent.id: agent.name
        for agent in db.execute(
            select(Agent).where(Agent.id.in_({s.agent_id for s in sessions}))
        ).scalars().all()
    }
    return [session_to_dict(db, session, agent_names.get(session.agent_id)) for session in sessions]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
def get_session(
    session_id: str,
    tool: str | None = Query(None, max_length=200),
    status_filter: str | None = Query(None, alias="status", pattern="^(success|failure|unknown)$"),
    q: str | None = Query(None, max_length=200),
    category: str | None = Query(None, max_length=50),
    start: datetime | None = None,
    end: datetime | None = None,
    order: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    agent = db.get(Agent, session.agent_id)
    events, total = _session_events(
        db,
        session,
        tool=tool,
        status_filter=status_filter,
        search=q,
        category=category,
        start=start,
        end=end,
        order=order,
        page=page,
        page_size=page_size,
    )
    incidents = db.execute(
        select(Incident)
        .where(Incident.session_id == session.id)
        .order_by(Incident.created_at.desc())
    ).scalars().all()
    tools = db.execute(
        select(Event.tool_name).where(Event.session_id == session.id).distinct().order_by(Event.tool_name)
    ).scalars().all()
    data = session_to_dict(db, session, agent.name if agent else None)
    data.update(
        {
            "events": events,
            "incidents": [incident_to_dict(db, incident) for incident in incidents],
            "total_events": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, math.ceil(total / page_size)),
            "tools": tools,
        }
    )
    return data


@router.get("/agents/{agent_id}/events", response_model=list[EventOut])
def agent_events(
    agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    if db.get(Agent, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return (
        db.execute(
            select(Event)
            .where(Event.agent_id == agent_id)
            .order_by(Event.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )


__all__ = ["router"]
