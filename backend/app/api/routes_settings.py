"""Settings, API keys, diagnostics, and intervention configuration."""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from ..ai.providers import ai_status
from ..config import get_settings
from ..core.security import create_api_key_record, require_admin, revoke_api_key_record
from ..database import get_db
from ..models import ApiKey, Event, Incident, Session, utcnow
from ..schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    DetectionOut,
    EventOut,
    GeneralSettingsOut,
    GeneralSettingsUpdate,
)
from ..services.serializers import audit
from ..services.settings import (
    DetectionSettings,
    GeneralSettings,
    get_detection_settings,
    get_general_settings,
    save_detection_settings,
    save_general_settings,
)

router = APIRouter(prefix="/api/v1", tags=["settings"])


@router.get("/settings/detection", response_model=DetectionSettings)
def read_detection_settings(
    db: DbSession = Depends(get_db), _: str = Depends(require_admin)
):
    return get_detection_settings(db)


@router.get("/settings/detection/defaults", response_model=DetectionSettings)
def detection_defaults(_: str = Depends(require_admin)):
    return DetectionSettings()


@router.put("/settings/detection", response_model=DetectionSettings)
def update_detection_settings(
    payload: DetectionSettings,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    save_detection_settings(db, payload)
    audit(
        db,
        "admin",
        "settings.detection_updated",
        "settings",
        "detection",
        payload.model_dump(),
    )
    db.commit()
    return payload


@router.get("/settings", response_model=GeneralSettingsOut)
def read_general_settings(
    db: DbSession = Depends(get_db), _: str = Depends(require_admin)
):
    general = get_general_settings(db)
    status = ai_status(db)
    data = general.model_dump()
    data.update(
        {
            "ai_enabled": status["enabled"],
            "ai_base_url": status["base_url"],
            "ai_model": status["model"],
            "ai_api_key_configured": status["api_key_configured"],
            "ai_active": status["configured"],
            "ai_provider": status["provider"],
            "ai_config_source": "database + environment",
        }
    )
    return data


@router.put("/settings", response_model=GeneralSettingsOut)
def update_general_settings(
    payload: GeneralSettingsUpdate,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    current = get_general_settings(db)
    changes = payload.model_dump(exclude_unset=True)
    merged = current.model_dump()
    merged.update(changes)
    try:
        new_settings = GeneralSettings.model_validate(merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if new_settings.ai_enabled:
        env = get_settings()
        if not (new_settings.ai_base_url or env.ai_base_url) or not (
            new_settings.ai_model or env.ai_model
        ):
            raise HTTPException(
                status_code=400,
                detail="Enabling AI requires an OpenAI-compatible base URL and a model name. "
                "Provide the API key through DEADLOOP_AI_API_KEY, never through this endpoint.",
            )
    save_general_settings(db, new_settings)
    audit(
        db,
        "admin",
        "settings.general_updated",
        "settings",
        "general",
        {key: value for key, value in changes.items() if key not in {"ai_base_url", "ai_model"}},
    )
    db.commit()
    return read_general_settings(db)


@router.get("/settings/ai-status")
def read_ai_status(db: DbSession = Depends(get_db), _: str = Depends(require_admin)):
    return ai_status(db)


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(db: DbSession = Depends(get_db), _: str = Depends(require_admin)):
    return db.execute(select(ApiKey).order_by(ApiKey.created_at.desc())).scalars().all()


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    payload: ApiKeyCreate,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    raw, record = create_api_key_record(db, payload.name)
    audit(db, "admin", "api_key.created", "api_key", record.id, {"name": payload.name})
    db.commit()
    return {
        "id": record.id,
        "name": record.name,
        "prefix": record.prefix,
        "created_at": record.created_at,
        "last_used_at": record.last_used_at,
        "revoked_at": record.revoked_at,
        "api_key": raw,
    }


@router.delete("/api-keys/{key_id}", response_model=ApiKeyOut)
def revoke_api_key(
    key_id: str, db: DbSession = Depends(get_db), _: str = Depends(require_admin)
):
    record = revoke_api_key_record(db, key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    audit(db, "admin", "api_key.revoked", "api_key", record.id, {"name": record.name})
    db.commit()
    db.refresh(record)
    return record


@router.post("/maintenance/prune")
def prune_retention(
    db: DbSession = Depends(get_db), _: str = Depends(require_admin)
):
    """Delete sessions whose latest event is older than the retention window.

    Entire sessions are removed so incident evidence never points at deleted
    events. Aggregate audit records for other resources are retained.
    """
    general = get_general_settings(db)
    cutoff = utcnow() - timedelta(days=general.retention_days)
    old_sessions = db.execute(
        select(Session)
        .where(Session.started_at < cutoff)
        .where(
            ~Session.id.in_(
                select(Event.session_id).where(Event.timestamp >= cutoff)
            )
        )
    ).scalars().all()
    ids = [session.id for session in old_sessions]
    if ids:
        db.execute(delete(Session).where(Session.id.in_(ids)))
    audit(
        db,
        "admin",
        "retention.pruned",
        "settings",
        "retention",
        {"sessions": len(ids), "retention_days": general.retention_days},
    )
    db.commit()
    return {"deleted_sessions": len(ids), "retention_days": general.retention_days, "cutoff": cutoff}


@router.get("/detections", response_model=list[DetectionOut])
def list_detections(
    limit: int = 100,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    from ..models import Detection

    limit = max(1, min(limit, 200))
    return db.execute(
        select(Detection).order_by(Detection.created_at.desc()).limit(limit)
    ).scalars().all()


__all__ = ["router"]
