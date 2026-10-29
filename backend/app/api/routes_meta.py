"""Health, authentication check, dashboard statistics, and demo control."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as DbSession

from .. import __version__
from ..ai.providers import ai_status
from ..config import get_settings
from ..core.security import require_admin
from ..database import get_db
from ..models import Agent, utcnow
from ..schemas import DemoRequest, DemoScenarioResult, HealthOut, StatsOverview
from ..services.analytics import build_overview
from ..services.demo import SCENARIOS, reset_demo_data, run_demo_scenario
from ..services.serializers import audit
from ..services.settings import get_general_settings

router = APIRouter(prefix="/api/v1", tags=["platform"])


@router.get("/health", response_model=HealthOut)
def health(db: DbSession = Depends(get_db)):
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database = "unavailable"
    general = get_general_settings(db)
    demo_mode = bool(db.scalar(select(func.count(Agent.id)).where(Agent.is_demo.is_(True))))
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "version": __version__,
        "environment": get_settings().environment,
        "ai_enabled": ai_status(db)["configured"],
        "intervention_mode": general.intervention_mode,
        "demo_mode": demo_mode,
        "time": utcnow().isoformat() + "Z",
    }


@router.get("/auth/check")
def auth_check(_: str = Depends(require_admin)):
    return {"ok": True, "role": "admin"}


@router.get("/stats/overview", response_model=StatsOverview)
def stats_overview(db: DbSession = Depends(get_db), _: str = Depends(require_admin)):
    return build_overview(db)


@router.post("/demo/scenarios/{scenario}", response_model=DemoScenarioResult)
def demo_scenario(
    scenario: str,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scenario. Available: {', '.join(SCENARIOS)}",
        )
    try:
        result = run_demo_scenario(db, scenario)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(
        db,
        "admin",
        "demo.scenario_run",
        "agent",
        result["agent_id"],
        {"scenario": scenario, "session_id": result["session_id"]},
    )
    db.commit()
    return result


@router.post("/demo/reset")
def demo_reset(
    payload: DemoRequest,
    db: DbSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="Demo reset requires explicit confirmation.",
        )
    result = reset_demo_data(db)
    audit(db, "admin", "demo.reset", "settings", "demo", result)
    db.commit()
    return result


__all__ = ["router"]
