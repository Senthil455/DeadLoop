"""Intervention policy enforcement and runtime adapters.

There is exactly one adapter: the deterministic demo simulator. Integrations
that cannot reliably pause an agent are reported as unsupported; DEADLOOP never
claims an agent was paused just because a request was recorded.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DbSession

from ..models import Agent, Incident, Intervention, Session, utcnow
from ..services.serializers import audit
from ..services.settings import get_general_settings


class PolicyError(Exception):
    """The configured policy forbids this intervention."""


class InterventionStateError(Exception):
    """The intervention is not in a valid state for this action."""


@dataclass
class RuntimeAck:
    acknowledged: bool
    simulated: bool
    runtime: str
    message: str


class SimulatorRuntime:
    runtime_name = "deadloop-simulator"

    def request_pause(self, agent: Agent, session: Session) -> RuntimeAck:
        if not agent.is_demo and agent.framework != "deadloop-simulator":
            return RuntimeAck(
                acknowledged=False,
                simulated=False,
                runtime=self.runtime_name,
                message=(
                    "No pause-capable runtime is connected for this agent. The request was "
                    "recorded, but the agent was not paused."
                ),
            )
        session.status = "paused"
        session.meta = {**(session.meta or {}), "paused_by": "deadloop-simulator"}
        return RuntimeAck(
            acknowledged=True,
            simulated=True,
            runtime=self.runtime_name,
            message="Simulated runtime acknowledged pause. No real agent process exists.",
        )


RUNTIME = SimulatorRuntime()


def runtime_supported(agent: Agent) -> bool:
    return bool(agent.is_demo or agent.framework == "deadloop-simulator")


def _execute(db: DbSession, intervention: Intervention, incident: Incident, actor: str) -> None:
    agent = db.get(Agent, incident.agent_id)
    session = db.get(Session, incident.session_id)
    if agent is None or session is None:
        intervention.execution_status = "FAILED"
        intervention.completed_at = utcnow()
        intervention.result = {
            "acknowledged": False,
            "message": "Agent or session no longer exists.",
        }
    else:
        ack = RUNTIME.request_pause(agent, session)
        intervention.simulated = ack.simulated
        intervention.execution_status = "ACKNOWLEDGED" if ack.acknowledged else "UNSUPPORTED"
        intervention.completed_at = utcnow()
        intervention.result = {
            "acknowledged": ack.acknowledged,
            "simulated": ack.simulated,
            "runtime": ack.runtime,
            "message": ack.message,
        }
    audit(
        db,
        actor=actor,
        action="intervention.executed",
        resource_type="incident",
        resource_id=incident.id,
        details={
            "intervention_id": intervention.id,
            "requested_action": intervention.requested_action,
            "execution_status": intervention.execution_status,
            "acknowledged": (intervention.result or {}).get("acknowledged", False),
            "simulated": intervention.simulated,
        },
    )
    db.flush()


def request_intervention(
    db: DbSession, incident: Incident, actor: str = "admin"
) -> Intervention:
    mode = get_general_settings(db).intervention_mode
    if mode in {"observe", "notify"}:
        raise PolicyError(
            f"Intervention mode '{mode}' does not permit pause requests. "
            "Change the policy explicitly in Settings before requesting one."
        )
    if incident.status in {"RESOLVED", "DISMISSED"}:
        raise PolicyError("Interventions cannot be requested for a closed incident.")

    intervention = Intervention(
        id=secrets.token_hex(16),
        incident_id=incident.id,
        agent_id=incident.agent_id,
        session_id=incident.session_id,
        requested_action="pause",
        policy_mode=mode,
        approval_status="PENDING" if mode == "approval_required" else "NOT_REQUIRED",
        execution_status="PENDING_APPROVAL" if mode == "approval_required" else "PENDING",
        initiated_by=actor,
        requested_at=utcnow(),
        simulated=False,
    )
    db.add(intervention)
    db.flush()
    audit(
        db,
        actor=actor,
        action="intervention.requested",
        resource_type="incident",
        resource_id=incident.id,
        details={
            "intervention_id": intervention.id,
            "mode": mode,
            "approval_required": mode == "approval_required",
            "requested_action": "pause",
        },
    )
    if mode == "automatic":
        # Automatic mode still requires an adapter acknowledgement.
        _execute(db, intervention, incident, actor)
    db.flush()
    return intervention


def approve_intervention(
    db: DbSession, intervention: Intervention, actor: str = "admin", note: str | None = None
) -> Intervention:
    incident = db.get(Incident, intervention.incident_id)
    if incident is None:
        raise InterventionStateError("Incident no longer exists.")
    if intervention.approval_status != "PENDING":
        raise InterventionStateError("This intervention is not awaiting approval.")
    mode = get_general_settings(db).intervention_mode
    if mode not in {"approval_required", "automatic"}:
        raise PolicyError(
            f"Current policy '{mode}' no longer permits executing interventions."
        )
    intervention.approval_status = "APPROVED"
    intervention.execution_status = "APPROVED"
    if note:
        intervention.result = {"approval_note": note[:1000]}
    audit(
        db,
        actor=actor,
        action="intervention.approved",
        resource_type="incident",
        resource_id=incident.id,
        details={"intervention_id": intervention.id, "note": note},
    )
    _execute(db, intervention, incident, actor)
    db.flush()
    return intervention


def reject_intervention(
    db: DbSession, intervention: Intervention, actor: str = "admin", note: str | None = None
) -> Intervention:
    if intervention.approval_status != "PENDING":
        raise InterventionStateError("This intervention is not awaiting approval.")
    incident = db.get(Incident, intervention.incident_id)
    intervention.approval_status = "REJECTED"
    intervention.execution_status = "NOT_EXECUTED"
    intervention.completed_at = utcnow()
    intervention.result = {"note": (note or "Rejected by operator")[:1000]}
    audit(
        db,
        actor=actor,
        action="intervention.rejected",
        resource_type="incident",
        resource_id=intervention.incident_id,
        details={"intervention_id": intervention.id, "note": note},
    )
    db.flush()
    return intervention


def intervention_dict(intervention: Intervention) -> dict[str, Any]:
    return {
        "id": intervention.id,
        "incident_id": intervention.incident_id,
        "agent_id": intervention.agent_id,
        "session_id": intervention.session_id,
        "requested_action": intervention.requested_action,
        "policy_mode": intervention.policy_mode,
        "approval_status": intervention.approval_status,
        "execution_status": intervention.execution_status,
        "initiated_by": intervention.initiated_by,
        "requested_at": intervention.requested_at,
        "completed_at": intervention.completed_at,
        "simulated": intervention.simulated,
        "result": intervention.result,
    }


__all__ = [
    "InterventionStateError",
    "PolicyError",
    "RuntimeAck",
    "approve_intervention",
    "intervention_dict",
    "reject_intervention",
    "request_intervention",
    "runtime_supported",
]
