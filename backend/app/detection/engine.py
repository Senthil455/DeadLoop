"""Deterministic loop and waste detection.

Design goals
------------
* No model call is required. Findings are explainable and reproducible.
* Every finding references the exact event IDs that produced it.
* Repeated calls alone are not treated as a malfunction. A finding also needs
  failure evidence or an explicit no-progress signal. This avoids punishing
  legitimate retries.
* Scores are heuristics in [0, 100], not probabilities.
* Analyzing an event twice cannot create a second incident: findings have a
  stable fingerprint and existing open findings are updated in place.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..core.fingerprint import canonical_json, semantic_similarity
from ..models import AuditLog, Detection, Event, Incident, Session, utcnow
from ..services.settings import DetectionSettings

CATEGORY_LABELS = {
    "exact_repetition": "Exact repetition",
    "semantic_repetition": "Near-duplicate repetition",
    "oscillation": "Oscillation",
    "repeated_failure": "Repeated failure",
    "no_progress": "No measurable progress",
    "budget_exceeded": "Budget threshold exceeded",
}

RECOMMENDED_ACTIONS = {
    "exact_repetition": (
        "Inspect the referenced events, confirm the agent still has a viable path, and pause the "
        "session through a supported runtime if it is still active. Do not re-run the same call "
        "with identical arguments."
    ),
    "semantic_repetition": (
        "Compare the inputs of the referenced calls. If they are functionally equivalent, change "
        "the strategy or pause the run before it burns more budget."
    ),
    "oscillation": (
        "Review the alternating actions and their failures. The agent may be retrying two steps "
        "without addressing the underlying error. Pause for human review if progress is still absent."
    ),
    "repeated_failure": (
        "Inspect the error category and recent inputs. Retrying without changing inputs or "
        "environment is unlikely to succeed; pause for human review if the pattern continues."
    ),
    "no_progress": (
        "Check the task checkpoint and recent trace. If no artifact or test state changed, pause the "
        "run and revise the plan. This finding relies on progress signals supplied by the agent."
    ),
    "budget_exceeded": (
        "Review the session budget and remaining work. Pause before further spend if the run has "
        "exceeded the configured tool-call, duration, token, or cost limit."
    ),
}


def severity_for(risk: int) -> str:
    if risk >= 85:
        return "CRITICAL"
    if risk >= 65:
        return "HIGH"
    if risk >= 40:
        return "MEDIUM"
    if risk >= 20:
        return "LOW"
    return "INFO"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def _progress_values(events: Iterable[Event]) -> list[bool]:
    values: list[bool] = []
    for event in events:
        progress = event.progress if isinstance(getattr(event, "progress", None), dict) else None
        if progress and isinstance(progress.get("made_progress"), bool):
            values.append(progress["made_progress"])
    return values


def _has_progress(events: Iterable[Event]) -> bool:
    return any(_progress_values(events))


def _explicit_no_progress(events: Iterable[Event]) -> bool:
    values = _progress_values(events)
    return bool(values) and not any(values)


def _preview(value: Any, limit: int = 240) -> str:
    try:
        text = canonical_json(value)
    except Exception:
        text = str(value)
    return text[:limit] + ("…" if len(text) > limit else "")


def _event_refs(events: list[Event], limit: int = 25) -> list[dict[str, Any]]:
    selected = sorted(events, key=lambda event: (event.timestamp, event.id))[-limit:]
    return [
        {
            "event_id": event.id,
            "timestamp": _iso(event.timestamp),
            "tool_name": event.tool_name,
            "status": event.status,
            "error_category": event.error_category,
            "input_preview": _preview(event.sanitized_input),
        }
        for event in selected
    ]


@dataclass
class Finding:
    category: str
    risk_score: int
    confidence: float
    title: str
    explanation: str
    evidence: dict[str, Any]
    recommended_action: str
    discriminator: str
    first_seen_at: datetime
    last_seen_at: datetime
    severity: str = field(init=False)

    def __post_init__(self) -> None:
        self.risk_score = _clamp(self.risk_score)
        self.confidence = round(max(0.0, min(1.0, self.confidence)), 2)
        self.severity = severity_for(self.risk_score)


def _window(events: list[Event], size: int) -> list[Event]:
    ordered = sorted(events, key=lambda event: (event.timestamp, event.id))
    return ordered[-size:]


def detect_exact_repetition(events: list[Event], settings: DetectionSettings) -> list[Finding]:
    config = settings.exact_repetition
    if not config.enabled:
        return []
    window = _window(events, config.window)
    groups: dict[tuple[str, str], list[Event]] = {}
    for event in window:
        groups.setdefault((event.tool_name, event.normalized_input_hash), []).append(event)

    findings: list[Finding] = []
    for (tool_name, input_hash), group in groups.items():
        if len(group) < config.min_occurrences:
            continue
        if _has_progress(group):
            continue
        failures = sum(1 for event in group if event.status == "failure")
        no_progress = _explicit_no_progress(group)
        if config.require_no_progress and not (no_progress or failures >= 2):
            continue
        occurrences = len(group)
        risk = 38 + min(20, (occurrences - config.min_occurrences) * 6)
        risk += min(15, failures * 5)
        if no_progress:
            risk += 12
        confidence = 0.9 if no_progress else (0.72 if failures else 0.55)
        ordered = sorted(group, key=lambda event: (event.timestamp, event.id))
        findings.append(
            Finding(
                category="exact_repetition",
                risk_score=risk,
                confidence=confidence,
                title=f"Exact repetition: {tool_name} called {occurrences}× with identical arguments",
                explanation=(
                    f"`{tool_name}` was invoked {occurrences} times with identical normalized "
                    f"arguments between {_iso(ordered[0].timestamp)} and "
                    f"{_iso(ordered[-1].timestamp)}. {failures} of those calls failed. "
                    + (
                        "The agent explicitly reported no progress during these calls. "
                        if no_progress
                        else "Repeated failures provide additional evidence that retrying the same "
                        "call is not resolving the task. "
                    )
                    + "Identical arguments mean the agent is not introducing new information between "
                    "attempts. The risk score is a transparent heuristic, not a probability of failure."
                ),
                evidence={
                    "event_ids": [event.id for event in ordered],
                    "sequence": _event_refs(ordered),
                    "metrics": {
                        "occurrences": occurrences,
                        "min_occurrences": config.min_occurrences,
                        "failures": failures,
                        "window_events": len(window),
                    },
                    "confidence_basis": (
                        "Explicit no-progress signal plus identical arguments."
                        if no_progress
                        else "Identical arguments plus repeated failures; progress signal unavailable."
                    ),
                    "uncertainty": (
                        "Repeated calls can be legitimate. This finding is supported by failures or "
                        "an explicit no-progress signal; review the trace before intervening."
                    ),
                },
                recommended_action=RECOMMENDED_ACTIONS["exact_repetition"],
                discriminator=f"{tool_name}:{input_hash}",
                first_seen_at=ordered[0].timestamp,
                last_seen_at=ordered[-1].timestamp,
            )
        )
    return findings


def detect_semantic_repetition(events: list[Event], settings: DetectionSettings) -> list[Finding]:
    config = settings.semantic_repetition
    if not config.enabled:
        return []
    window = _window(events, config.window)
    by_tool: dict[str, list[Event]] = {}
    for event in window:
        by_tool.setdefault(event.tool_name, []).append(event)

    findings: list[Finding] = []
    for tool_name, tool_events in by_tool.items():
        if len(tool_events) < config.min_occurrences or len(tool_events) > 50:
            continue
        # Cluster near-duplicate inputs. Exact repetitions are handled separately.
        best: list[Event] = []
        for pivot in tool_events:
            cluster = [
                candidate
                for candidate in tool_events
                if semantic_similarity(pivot.sanitized_input, candidate.sanitized_input)
                >= config.similarity_threshold
            ]
            if len(cluster) > len(best):
                best = cluster
        hashes = {event.normalized_input_hash for event in best}
        if len(best) < config.min_occurrences or len(hashes) < 2:
            continue
        if _has_progress(best):
            continue
        failures = sum(1 for event in best if event.status == "failure")
        no_progress = _explicit_no_progress(best)
        if failures == 0 and not no_progress:
            continue
        ordered = sorted(best, key=lambda event: (event.timestamp, event.id))
        risk = 34 + min(18, len(best) * 3) + min(10, failures * 3)
        findings.append(
            Finding(
                category="semantic_repetition",
                risk_score=risk,
                confidence=0.68 if not no_progress else 0.82,
                title=f"Near-duplicate repetition: {tool_name} called {len(best)}× with equivalent inputs",
                explanation=(
                    f"`{tool_name}` was called {len(best)} times with inputs whose normalized "
                    f"similarity met the configured threshold of {config.similarity_threshold:.2f}. "
                    f"The calls were not byte-identical, but they are functionally similar and "
                    f"{failures} failed. The agent appears to be varying formatting or insignificant "
                    "arguments rather than changing its approach."
                ),
                evidence={
                    "event_ids": [event.id for event in ordered],
                    "sequence": _event_refs(ordered),
                    "metrics": {
                        "occurrences": len(best),
                        "distinct_exact_inputs": len(hashes),
                        "similarity_threshold": config.similarity_threshold,
                        "failures": failures,
                    },
                    "confidence_basis": "Normalized argument similarity plus failure evidence.",
                    "uncertainty": (
                        "Similarity is computed from canonicalized inputs. Semantically different "
                        "tasks can share surface structure; inspect inputs before intervening."
                    ),
                },
                recommended_action=RECOMMENDED_ACTIONS["semantic_repetition"],
                discriminator=f"{tool_name}:near_duplicate",
                first_seen_at=ordered[0].timestamp,
                last_seen_at=ordered[-1].timestamp,
            )
        )
    return findings


def detect_oscillation(events: list[Event], settings: DetectionSettings) -> list[Finding]:
    config = settings.oscillation
    if not config.enabled:
        return []
    window = _window(events, config.window)
    if len(window) < config.min_cycles * 2:
        return []

    ordered = sorted(window, key=lambda event: (event.timestamp, event.id))
    # Longest alternating suffix (A-B-A-B...), keyed by tool/action signature.
    suffix = [ordered[-1]]
    for event in reversed(ordered[:-1]):
        previous = suffix[-1]
        if event.tool_name == previous.tool_name:
            break
        suffix.append(event)
    suffix.reverse()
    cycles = len(suffix) // 2
    distinct_tools = {event.tool_name for event in suffix}
    if cycles < config.min_cycles or len(distinct_tools) < 2:
        return []
    if _has_progress(suffix):
        return []
    failures = sum(1 for event in suffix if event.status == "failure")
    no_progress = _explicit_no_progress(suffix)
    if failures == 0 and not no_progress:
        return []

    tools = sorted(distinct_tools)
    risk = 42 + min(30, cycles * 7) + min(15, failures * 3)
    return [
        Finding(
            category="oscillation",
            risk_score=risk,
            confidence=0.86 if no_progress else 0.7,
            title=f"Oscillation: {' ↔ '.join(tools)} repeated for {cycles} cycles",
            explanation=(
                f"The agent alternated between `{tools[0]}` and `{tools[1]}` for {cycles} consecutive "
                f"cycles ({len(suffix)} tool calls) with {failures} failures. No successful progress "
                "signal was observed during the alternating sequence. Alternation can be legitimate, "
                "but repeated cycles with unchanged failures suggest the agent is retrying two steps "
                "without addressing the underlying error."
            ),
            evidence={
                "event_ids": [event.id for event in suffix],
                "sequence": _event_refs(suffix),
                "metrics": {
                    "cycles": cycles,
                    "tools": tools,
                    "failures": failures,
                    "min_cycles": config.min_cycles,
                },
                "confidence_basis": (
                    "Alternating tool sequence with failure or explicit no-progress evidence."
                ),
                "uncertainty": (
                    "Two-step workflows naturally alternate. This finding requires repeated cycles "
                    "plus failure or no-progress evidence."
                ),
            },
            recommended_action=RECOMMENDED_ACTIONS["oscillation"],
            discriminator=f"{tools[0]}|{tools[1]}",
            first_seen_at=suffix[0].timestamp,
            last_seen_at=suffix[-1].timestamp,
        )
    ]


def detect_repeated_failures(events: list[Event], settings: DetectionSettings) -> list[Finding]:
    config = settings.repeated_failure
    if not config.enabled:
        return []
    window = _window(events, config.window)
    groups: dict[tuple[str, str], list[Event]] = {}
    for event in window:
        if event.status != "failure":
            continue
        key = (event.tool_name, event.error_category or "unknown")
        groups.setdefault(key, []).append(event)

    findings: list[Finding] = []
    for (tool_name, error_category), group in groups.items():
        if len(group) < config.min_failures:
            continue
        if _has_progress(group):
            continue
        ordered = sorted(group, key=lambda event: (event.timestamp, event.id))
        identical = len({event.normalized_input_hash for event in group}) <= 1
        risk = 34 + min(38, (len(group) - config.min_failures) * 10) + (8 if identical else 0)
        findings.append(
            Finding(
                category="repeated_failure",
                risk_score=risk,
                confidence=0.9,
                title=f"Repeated failure: {tool_name} failed {len(group)}× ({error_category})",
                explanation=(
                    f"`{tool_name}` failed {len(group)} times with error category "
                    f"`{error_category}` between {_iso(ordered[0].timestamp)} and "
                    f"{_iso(ordered[-1].timestamp)}. "
                    + (
                        "All failures used identical normalized inputs. "
                        if identical
                        else "The inputs varied, but the same error category persisted. "
                    )
                    + "Retrying without changing the failing condition is unlikely to make progress. "
                    "The risk score is a heuristic, not a probability."
                ),
                evidence={
                    "event_ids": [event.id for event in ordered],
                    "sequence": _event_refs(ordered),
                    "metrics": {
                        "failures": len(group),
                        "min_failures": config.min_failures,
                        "error_category": error_category,
                        "identical_inputs": identical,
                    },
                    "confidence_basis": "Repeated failures with the same tool and error category.",
                    "uncertainty": (
                        "A failure category can be transient or environmental. Check whether the "
                        "agent retried with meaningfully different conditions."
                    ),
                },
                recommended_action=RECOMMENDED_ACTIONS["repeated_failure"],
                discriminator=f"{tool_name}:{error_category}",
                first_seen_at=ordered[0].timestamp,
                last_seen_at=ordered[-1].timestamp,
            )
        )
    return findings


def detect_no_progress(events: list[Event], settings: DetectionSettings) -> list[Finding]:
    config = settings.no_progress
    if not config.enabled:
        return []
    window = _window(events, config.window)
    if len(window) < config.min_events:
        return []
    values = _progress_values(window)
    # Without explicit progress signals, report uncertainty by remaining silent.
    if len(values) < 3 or any(values):
        return []
    ordered = sorted(window, key=lambda event: (event.timestamp, event.id))
    risk = 36 + min(18, (len(window) - config.min_events) * 2)
    return [
        Finding(
            category="no_progress",
            risk_score=risk,
            confidence=0.62,
            title=f"No progress reported across {len(window)} events",
            explanation=(
                f"The most recent {len(window)} events contain explicit progress signals, and every "
                "signal reports that no measurable progress was made. "
                f"{sum(1 for event in window if event.status == 'success')} calls succeeded "
                "technically, so activity alone is not evidence of task advancement. This finding is "
                "based on agent-supplied progress signals and may be incomplete."
            ),
            evidence={
                "event_ids": [event.id for event in ordered],
                "sequence": _event_refs(ordered),
                "metrics": {
                    "events": len(window),
                    "progress_signals": len(values),
                    "true_progress_signals": sum(1 for value in values if value),
                },
                "confidence_basis": "Explicit no-progress signals on at least three events.",
                "uncertainty": (
                    "Progress is self-reported by the instrumented agent. Absence of a signal is not "
                    "treated as evidence of failure."
                ),
            },
            recommended_action=RECOMMENDED_ACTIONS["no_progress"],
            discriminator="session",
            first_seen_at=ordered[0].timestamp,
            last_seen_at=ordered[-1].timestamp,
        )
    ]


def detect_budget(
    events: list[Event],
    settings: DetectionSettings,
    session: Session | None,
) -> list[Finding]:
    config = settings.budget
    if not config.enabled or session is None:
        return []
    window = _window(events, 60)
    if not window:
        return []
    ordered = sorted(window, key=lambda event: (event.timestamp, event.id))
    event_count = session.event_count or len(events)
    duration_seconds = 0.0
    if window:
        duration_seconds = max(
            0.0, (ordered[-1].timestamp - (session.started_at or ordered[0].timestamp)).total_seconds()
        )
    tokens = sum(event.tokens or 0 for event in window)
    cost = sum(event.cost_usd or 0.0 for event in window)
    consecutive_failures = 0
    for event in reversed(ordered):
        if event.status == "failure":
            consecutive_failures += 1
        else:
            break

    reasons: list[str] = []
    score = 0
    if event_count > config.max_tool_calls:
        reasons.append(f"{event_count} tool calls exceeded the limit of {config.max_tool_calls}")
        score = max(score, 45 + min(25, (event_count - config.max_tool_calls) // 2))
    if duration_seconds > config.max_duration_seconds:
        reasons.append(
            f"session duration {int(duration_seconds)}s exceeded {config.max_duration_seconds}s"
        )
        score = max(score, 50)
    if consecutive_failures >= config.max_consecutive_failures:
        reasons.append(
            f"{consecutive_failures} consecutive failures reached the limit of "
            f"{config.max_consecutive_failures}"
        )
        score = max(score, 55)
    if config.max_tokens and tokens > config.max_tokens:
        reasons.append(f"{tokens} tokens exceeded the limit of {config.max_tokens}")
        score = max(score, 48)
    if config.max_cost_usd and cost > config.max_cost_usd:
        reasons.append(f"${cost:.2f} exceeded the cost limit of ${config.max_cost_usd:.2f}")
        score = max(score, 52)
    if not reasons:
        return []

    return [
        Finding(
            category="budget_exceeded",
            risk_score=score,
            confidence=0.95,
            title="Session budget threshold exceeded",
            explanation=(
                "A configured session budget was exceeded: " + "; ".join(reasons) + ". "
                "This is a deterministic threshold, not a model judgment. The referenced events are "
                "the most recent activity in the session."
            ),
            evidence={
                "event_ids": [event.id for event in ordered],
                "sequence": _event_refs(ordered),
                "metrics": {
                    "event_count": event_count,
                    "duration_seconds": round(duration_seconds, 1),
                    "tokens": tokens,
                    "cost_usd": round(cost, 6),
                    "consecutive_failures": consecutive_failures,
                    "limits": config.model_dump(),
                },
                "confidence_basis": "Deterministic comparison against configured budgets.",
                "uncertainty": "Budget limits are operator-defined and may need tuning per workload.",
            },
            recommended_action=RECOMMENDED_ACTIONS["budget_exceeded"],
            discriminator="session",
            first_seen_at=ordered[0].timestamp,
            last_seen_at=ordered[-1].timestamp,
        )
    ]


def detect_all(
    events: list[Event],
    settings: DetectionSettings,
    session: Session | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    for detector in (
        detect_exact_repetition,
        detect_semantic_repetition,
        detect_oscillation,
        detect_repeated_failures,
        detect_no_progress,
    ):
        findings.extend(detector(events, settings))
    findings.extend(detect_budget(events, settings, session))
    # Deterministic ordering makes tests and incident ids stable.
    return sorted(findings, key=lambda finding: (finding.category, finding.discriminator))


def _fingerprint(session_id: str, finding: Finding) -> str:
    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
    discriminator = hashlib.sha256(finding.discriminator.encode("utf-8")).hexdigest()[:32]
    return f"{finding.category}:{session_key}:{discriminator}"


def persist_findings(
    db: DbSession,
    agent_id: str,
    session_id: str,
    findings: list[Finding],
) -> tuple[int, int]:
    """Persist findings, updating existing open detections instead of duplicating."""
    detections_created = 0
    incidents_created = 0
    now = utcnow()
    for finding in findings:
        fingerprint = _fingerprint(session_id, finding)
        existing = db.execute(
            select(Detection)
            .where(Detection.fingerprint == fingerprint)
            .order_by(Detection.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            incident = db.execute(
                select(Incident).where(Incident.detection_id == existing.id)
            ).scalar_one_or_none()
            if incident and incident.status in {"DISMISSED", "RESOLVED"}:
                # Respect a human decision. Do not resurface the same pattern
                # for this session.
                continue
            existing.risk_score = max(existing.risk_score, finding.risk_score)
            existing.severity = severity_for(existing.risk_score)
            existing.confidence = max(existing.confidence, finding.confidence)
            existing.evidence = finding.evidence
            existing.explanation = finding.explanation
            existing.last_seen_at = finding.last_seen_at
            existing.updated_at = now
            if incident:
                incident.risk_score = existing.risk_score
                incident.severity = existing.severity
                incident.updated_at = now
            continue

        detection = Detection(
            id=secrets.token_hex(16),
            agent_id=agent_id,
            session_id=session_id,
            category=finding.category,
            severity=finding.severity,
            risk_score=finding.risk_score,
            confidence=finding.confidence,
            fingerprint=fingerprint,
            evidence=finding.evidence,
            explanation=finding.explanation,
            recommended_action=finding.recommended_action,
            first_seen_at=finding.first_seen_at,
            last_seen_at=finding.last_seen_at,
            created_at=now,
            updated_at=now,
        )
        db.add(detection)
        db.flush()
        incident = Incident(
            id=secrets.token_hex(16),
            detection_id=detection.id,
            agent_id=agent_id,
            session_id=session_id,
            title=finding.title,
            status="OPEN",
            severity=finding.severity,
            risk_score=finding.risk_score,
            created_at=now,
            updated_at=now,
        )
        db.add(incident)
        db.flush()
        db.add(
            AuditLog(
                id=secrets.token_hex(16),
                actor="system:detector",
                action="incident.created",
                resource_type="incident",
                resource_id=incident.id,
                details={
                    "category": finding.category,
                    "severity": finding.severity,
                    "risk_score": finding.risk_score,
                    "event_ids": finding.evidence.get("event_ids", [])[:25],
                },
            )
        )
        detections_created += 1
        incidents_created += 1
    return detections_created, incidents_created


def analyze_session(db: DbSession, session: Session, agent_configuration: dict[str, Any] | None = None) -> tuple[int, int]:
    from ..services.settings import get_detection_settings

    settings = get_detection_settings(db, agent_configuration)
    max_window = max(
        settings.exact_repetition.window,
        settings.semantic_repetition.window,
        settings.oscillation.window,
        settings.repeated_failure.window,
        settings.no_progress.window,
        60,
    )
    events = (
        db.execute(
            select(Event)
            .where(Event.session_id == session.id)
            .order_by(Event.timestamp.desc(), Event.id.desc())
            .limit(max_window)
        )
        .scalars()
        .all()
    )
    if not events:
        return 0, 0
    findings = detect_all(events, settings, session)
    return persist_findings(db, session.agent_id, session.id, findings)


__all__ = [
    "CATEGORY_LABELS",
    "Finding",
    "analyze_session",
    "detect_all",
    "detect_budget",
    "detect_exact_repetition",
    "detect_no_progress",
    "detect_oscillation",
    "detect_repeated_failures",
    "detect_semantic_repetition",
    "persist_findings",
    "severity_for",
]
