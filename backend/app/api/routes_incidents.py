"""Incident management, notes, AI explanations, and interventions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..ai.providers import explain_incident
from ..core.security import require_admin
from ..database import get_db
from ..interventions.service import (
    InterventionStateError,
    PolicyError,
    approve_intervention,
    reject_intervention,
    request_intervention,
)
from ..models import Incident, Intervention, utcnow
from ..schemas import (
    IncidentDetail,
    IncidentOut,
    IncidentStatusUpdate,
    InterventionDecision,
    InterventionOut,
    InterventionRequest,
    NoteCreate,
)
from ..services.serializers import audit, incident_to_dict

router = APIRouter(prefix="/api/v1", tags=["incidents"])

OPEN_STATUSES = ("OPEN", "ACKNOWLEDGED")


@router.get("/incidents", response_model=list[IncidentOut])
def list_incidents(
    status_filter: str | None = Query(None, alias="status", pattern="^(OPEN|ACKNOWLEDGED|RESOLVED|DISMISSED)$"),
    severity: str | None = Query(None, pattern="^(INFO|LOW|MEDIUM|HIGH|CRITICAL)$"),
    category: str | None = Query(None, max_length=50),
    agent_id: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=200),
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    query = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(Incident.status == status_filter)
    if severity:
        query = query.where(Incident.severity == severity)
    if agent_id:
        query = query.where(Incident.agent_id == agent_id)
    if q:
        query = query.where(Incident.title.ilike(f"%{q}%"))
    if category:
        from ..models import Detection

        query = query.join(Detection, Detection.id == Incident.detection_id).where(
            Detection.category == category
        )
    incidents = db.execute(query).scalars().all()
    return [incident_to_dict(db, incident) for incident in incidents]


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(
    incident_id: str, db: DbSession = Depends(get_db), _: str = Depends(require_admin)
):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return incident_to_dict(db, incident, include_detail=True)


def _transition_allowed(current: str, target: str) -> bool:
    if current in {"RESOLVED", "DISMISSED"}:
        return False
    if target == "ACKNOWLEDGED":
        return current == "OPEN"
    if target in {"RESOLVED", "DISMISSED"}:
        return current in OPEN_STATUSES
    return False


@router.post("/incidents/{incident_id}/status", response_model=IncidentDetail)
def update_incident_status(
    incident_id: str,
    payload: IncidentStatusUpdate,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    if not _transition_allowed(incident.status, payload.status):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move an incident from {incident.status} to {payload.status}.",
        )
    previous = incident.status
    incident.status = payload.status
    incident.updated_at = utcnow()
    if payload.status == "RESOLVED":
        incident.resolved_at = utcnow()
    audit(
        db,
        "admin",
        f"incident.{payload.status.lower()}",
        "incident",
        incident.id,
        {
            "from": previous,
            "to": payload.status,
            "note": payload.note,
        },
    )
    db.commit()
    db.refresh(incident)
    return incident_to_dict(db, incident, include_detail=True)


@router.post("/incidents/{incident_id}/notes", response_model=IncidentDetail)
def add_note(
    incident_id: str,
    payload: NoteCreate,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    from ..models import IncidentNote

    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    note = IncidentNote(
        id=__import__("secrets").token_hex(16),
        incident_id=incident.id,
        author="admin",
        body=payload.body,
        created_at=utcnow(),
    )
    db.add(note)
    incident.updated_at = utcnow()
    audit(db, "admin", "incident.note_added", "incident", incident.id, {"length": len(payload.body)})
    db.commit()
    db.refresh(incident)
    return incident_to_dict(db, incident, include_detail=True)


@router.post("/incidents/{incident_id}/explain")
def explain(
    incident_id: str,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    result = explain_incident(db, incident)
    db.commit()
    return result.to_dict()


@router.post("/incidents/{incident_id}/interventions", response_model=InterventionOut)
def request_pause(
    incident_id: str,
    payload: InterventionRequest,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    try:
        intervention = request_intervention(db, incident, actor="admin")
    except PolicyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(intervention)
    return intervention


@router.post("/interventions/{intervention_id}/approve", response_model=InterventionOut)
def approve(
    intervention_id: str,
    payload: InterventionDecision | None = None,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    intervention = db.get(Intervention, intervention_id)
    if intervention is None:
        raise HTTPException(status_code=404, detail="Intervention not found.")
    try:
        approve_intervention(
            db, intervention, actor="admin", note=payload.note if payload else None
        )
    except (PolicyError, InterventionStateError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(intervention)
    return intervention


@router.post("/interventions/{intervention_id}/reject", response_model=InterventionOut)
def reject(
    intervention_id: str,
    payload: InterventionDecision | None = None,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    intervention = db.get(Intervention, intervention_id)
    if intervention is None:
        raise HTTPException(status_code=404, detail="Intervention not found.")
    try:
        reject_intervention(
            db, intervention, actor="admin", note=payload.note if payload else None
        )
    except InterventionStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(intervention)
    return intervention


__all__ = ["router"]
