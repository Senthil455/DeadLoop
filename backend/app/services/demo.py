"""Deterministic demo scenarios.

All scenarios go through the same validation, persistence, detection, and
incident code as production ingestion. They are explicitly marked as demo data
and can be removed without touching real agents.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from ..models import Agent, AuditLog, Detection, Event, Incident, Intervention, Session, utcnow
from ..schemas import EventIn
from ..services.ingestion import ingest_payloads


SCENARIOS = (
    "healthy",
    "exact_repetition",
    "oscillation",
    "repeated_failure",
    "ambiguous",
    "recovery",
)


def _event(
    *,
    event_id: str,
    agent_id: str,
    session_id: str,
    timestamp,
    tool_name: str,
    action: str,
    input_value: Any,
    output_value: Any = None,
    status: str = "success",
    error_category: str | None = None,
    progress: bool | None = None,
    task: str | None = None,
    duration_ms: int = 120,
    retry_count: int = 0,
    tokens: int | None = None,
) -> EventIn:
    return EventIn(
        event_id=event_id,
        agent_id=agent_id,
        session_id=session_id,
        timestamp=timestamp,
        tool_name=tool_name,
        action=action,
        input=input_value,
        output=output_value,
        status=status,
        error_category=error_category,
        progress={"made_progress": progress} if progress is not None else None,
        task=task,
        duration_ms=duration_ms,
        retry_count=retry_count,
        tokens=tokens,
        model="demo/simulator",
        metadata={"demo": True},
    )


def _healthy_events(agent_id: str, session_id: str, start) -> list[EventIn]:
    plan = [
        ("read_file", "Read authentication module", {"path": "app/auth.py"}, {"lines": 180}, True, 40),
        ("search_web", "Find refresh-token best practices", {"query": "refresh token rotation"}, {"results": 5}, True, 75),
        ("write_file", "Add rotation helper", {"path": "app/auth.py", "patch": "add rotate_token()"}, {"bytes": 420}, True, 95),
        ("run_tests", "Run auth test suite", {"suite": "auth"}, {"passed": 12, "failed": 1}, False, 230),
        ("read_file", "Inspect failing assertion", {"path": "tests/test_auth.py", "line": 88}, {"assertion": "expiry boundary"}, True, 35),
        ("edit_file", "Fix boundary comparison", {"path": "app/auth.py", "change": "<= instead of <"}, {"applied": True}, True, 80),
        ("run_tests", "Re-run auth test suite", {"suite": "auth"}, {"passed": 13, "failed": 0}, True, 210),
        ("write_file", "Update changelog", {"path": "CHANGELOG.md", "entry": "token rotation"}, {"bytes": 180}, True, 45),
        ("finish", "Report completion", {"goal": "token rotation", "checkpoint": "all tests pass"}, {"status": "done"}, True, 10),
    ]
    events = []
    for index, (tool, action, args, output, progressed, duration) in enumerate(plan):
        events.append(
            _event(
                event_id=f"healthy-{index}-{secrets.token_hex(3)}",
                agent_id=agent_id,
                session_id=session_id,
                timestamp=start + timedelta(seconds=index * 9),
                tool_name=tool,
                action=action,
                input_value=args,
                output_value=output,
                status="success",
                progress=progressed,
                task="Add refresh-token rotation and fix the failing expiry test",
                duration_ms=duration,
                tokens=800 + index * 120,
            )
        )
    return events


def _exact_events(agent_id: str, session_id: str, start) -> list[EventIn]:
    args = {"query": "database connection error timeout retry"}
    events = []
    for index in range(5):
        events.append(
            _event(
                event_id=f"exact-{index}-{secrets.token_hex(3)}",
                agent_id=agent_id,
                session_id=session_id,
                timestamp=start + timedelta(seconds=index * 7),
                tool_name="search_web",
                action="Search for a fix",
                input_value=args,
                output_value={"error": "upstream timeout"},
                status="failure",
                error_category="connection_timeout",
                progress=False,
                task="Diagnose and fix the database connection timeout",
                duration_ms=4000,
                retry_count=index,
                tokens=300,
            )
        )
    return events


def _oscillation_events(agent_id: str, session_id: str, start) -> list[EventIn]:
    events = []
    for index in range(8):
        if index % 2 == 0:
            tool = "edit_file"
            action = "Patch pool configuration"
            args = {"path": "app/db.py", "attempt": index // 2 + 1, "patch": "pool_recycle=60"}
            output = {"error": "syntax error introduced"}
            error = "syntax_error"
        else:
            tool = "run_tests"
            action = "Run database tests"
            args = {"suite": "db", "attempt": index // 2 + 1}
            output = {"failed": 3, "error": "pool timeout"}
            error = "test_failure"
        events.append(
            _event(
                event_id=f"osc-{index}-{secrets.token_hex(3)}",
                agent_id=agent_id,
                session_id=session_id,
                timestamp=start + timedelta(seconds=index * 8),
                tool_name=tool,
                action=action,
                input_value=args,
                output_value=output,
                status="failure",
                error_category=error,
                progress=False,
                task="Fix the database pool timeout",
                duration_ms=850,
                retry_count=index,
                tokens=420,
            )
        )
    return events


def _repeated_failure_events(agent_id: str, session_id: str, start) -> list[EventIn]:
    events = []
    for index in range(7):
        events.append(
            _event(
                event_id=f"failure-{index}-{secrets.token_hex(3)}",
                agent_id=agent_id,
                session_id=session_id,
                timestamp=start + timedelta(seconds=index * 6),
                tool_name="call_api",
                action="Fetch enrichment data",
                input_value={"record": 42, "attempt": index},
                output_value={"error": "429 too many requests"},
                status="failure",
                error_category="rate_limit",
                progress=False,
                task="Enrich record 42",
                duration_ms=250,
                retry_count=index,
                tokens=90,
            )
        )
    return events


def _ambiguous_events(agent_id: str, session_id: str, start) -> list[EventIn]:
    events = []
    for index in range(5):
        events.append(
            _event(
                event_id=f"amb-{index}-{secrets.token_hex(3)}",
                agent_id=agent_id,
                session_id=session_id,
                timestamp=start + timedelta(seconds=index * 5),
                tool_name="search_web",
                action="Check release status",
                input_value={"query": "release status"},
                output_value={"page": index + 1, "new_findings": index},
                status="success",
                progress=True,
                task="Gather release notes",
                duration_ms=300,
                tokens=200,
            )
        )
    return events


def run_demo_scenario(db: DbSession, scenario: str) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario}'.")
    suffix = secrets.token_hex(4)
    base_scenario = "exact_repetition" if scenario == "recovery" else scenario
    labels = {
        "healthy": ("Healthy Agent", "A normal task with varied tools and explicit progress."),
        "exact_repetition": ("Repetition Lab", "Repeats one failing search with identical arguments."),
        "oscillation": ("Oscillation Lab", "Alternates between edit and test without progress."),
        "repeated_failure": ("Failure Lab", "Retries an API call until the rate limit repeats."),
        "ambiguous": ("Ambiguous Lab", "Repeats a successful call while reporting progress."),
        "recovery": ("Recovery Lab", "Loop used for the approval and pause workflow."),
    }
    name, description = labels[scenario]
    agent_id = f"demo-{scenario}-{suffix}"
    session_id = f"demo-session-{scenario}-{suffix}"
    start = utcnow() - timedelta(minutes=2)
    agent = Agent(
        id=agent_id,
        name=name,
        description=description,
        framework="deadloop-simulator",
        status="active",
        is_demo=True,
        created_at=utcnow(),
        last_seen_at=start,
        configuration={"demo": True},
    )
    db.add(agent)
    db.flush()

    if base_scenario == "healthy":
        events = _healthy_events(agent_id, session_id, start)
    elif base_scenario == "exact_repetition":
        events = _exact_events(agent_id, session_id, start)
    elif base_scenario == "oscillation":
        events = _oscillation_events(agent_id, session_id, start)
    elif base_scenario == "repeated_failure":
        events = _repeated_failure_events(agent_id, session_id, start)
    else:
        events = _ambiguous_events(agent_id, session_id, start)

    result = ingest_payloads(db, events)
    detections = db.execute(
        select(Detection).where(Detection.session_id == session_id)
    ).scalars().all()
    incidents = db.execute(
        select(Incident).where(Incident.session_id == session_id)
    ).scalars().all()
    note = {
        "healthy": "Healthy scenario completed. No high-severity incident should be raised.",
        "exact_repetition": "Identical failing search calls should produce a repetition finding.",
        "oscillation": "Alternating edit/test failures should produce an oscillation finding.",
        "repeated_failure": "Repeated rate-limit failures should produce a repeated-failure finding.",
        "ambiguous": (
            "Repeated successful calls with explicit progress are intentionally not escalated. "
            "No incident is expected."
        ),
        "recovery": (
            "Loop created for the intervention workflow. Request a pause, approve it, and verify "
            "the simulator acknowledges it."
        ),
    }[scenario]
    return {
        "scenario": scenario,
        "agent_id": agent_id,
        "session_id": session_id,
        "events_created": result["accepted"],
        "detections_created": result["detections_created"],
        "incident_ids": [incident.id for incident in incidents],
        "detections": [detection.category for detection in detections],
        "note": note,
    }


def reset_demo_data(db: DbSession) -> dict[str, Any]:
    demo_agents = db.execute(select(Agent).where(Agent.is_demo.is_(True))).scalars().all()
    agent_ids = [agent.id for agent in demo_agents]
    if not agent_ids:
        return {"deleted_agents": 0, "deleted_events": 0, "deleted_incidents": 0}
    session_ids = db.execute(
        select(Session.id).where(Session.agent_id.in_(agent_ids))
    ).scalars().all()
    incident_ids = db.execute(
        select(Incident.id).where(Incident.agent_id.in_(agent_ids))
    ).scalars().all()
    event_count = (
        db.execute(select(Event.id).where(Event.agent_id.in_(agent_ids))).scalars().all()
    )
    db.execute(
        delete(AuditLog).where(
            AuditLog.resource_type.in_(["incident", "agent"]),
            AuditLog.resource_id.in_(list(incident_ids) + agent_ids),
        )
    )
    db.execute(delete(Agent).where(Agent.id.in_(agent_ids)))
    db.flush()
    return {
        "deleted_agents": len(agent_ids),
        "deleted_events": len(event_count),
        "deleted_incidents": len(incident_ids),
        "deleted_sessions": len(session_ids),
    }


__all__ = ["SCENARIOS", "reset_demo_data", "run_demo_scenario"]
