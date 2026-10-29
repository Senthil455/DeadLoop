"""Unit tests for deterministic detectors and fingerprints."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.fingerprint import canonical_json, fingerprint, semantic_similarity
from app.detection.engine import (
    detect_all,
    detect_budget,
    detect_exact_repetition,
    detect_no_progress,
    detect_oscillation,
    detect_repeated_failures,
    detect_semantic_repetition,
    severity_for,
)
from app.models import Event, Session
from app.services.settings import DetectionSettings

BASE = datetime(2026, 10, 29, 12, 0, 0)


def make_event(
    index: int,
    *,
    tool: str = "search_web",
    args: dict | None = None,
    status: str = "success",
    progress: bool | None = None,
    error: str | None = None,
    agent: str = "agent-1",
    session: str = "session-1",
) -> Event:
    args = args if args is not None else {"query": "same"}
    return Event(
        id=f"evt-{index}",
        agent_id=agent,
        session_id=session,
        timestamp=BASE + timedelta(seconds=index),
        tool_name=tool,
        action="act",
        normalized_input_hash=fingerprint(args),
        semantic_hash=fingerprint(args, lowercase=True),
        status=status,
        error_category=error,
        retry_count=0,
        duration_ms=10,
        sanitized_input=args,
        sanitized_output={"ok": status == "success"},
        progress={"made_progress": progress} if progress is not None else None,
    )


def test_fingerprint_is_stable_across_key_order_and_whitespace():
    assert fingerprint({"b": 2, "a": "  hello   world "}) == fingerprint(
        {"a": "hello world", "b": 2}
    )
    assert fingerprint({"a": 1, "timestamp": "one"}) == fingerprint(
        {"a": 1, "timestamp": "two"}
    )
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_semantic_similarity_handles_case_and_spacing():
    assert semantic_similarity({"query": "Database  Timeout"}, {"query": "database timeout"}) == 1.0
    assert semantic_similarity({"query": "alpha"}, {"query": "beta"}) < 0.9


def test_exact_repetition_below_threshold_does_not_trigger():
    events = [make_event(i, status="failure", error="timeout", progress=False) for i in range(2)]
    assert detect_exact_repetition(events, DetectionSettings()) == []


def test_exact_repetition_triggers_with_failures_and_no_progress():
    events = [make_event(i, status="failure", error="timeout", progress=False) for i in range(3)]
    findings = detect_exact_repetition(events, DetectionSettings())
    assert len(findings) == 1
    finding = findings[0]
    assert finding.category == "exact_repetition"
    assert finding.severity in {"MEDIUM", "HIGH", "CRITICAL"}
    assert 0 <= finding.risk_score <= 100
    assert finding.evidence["event_ids"] == ["evt-0", "evt-1", "evt-2"]
    assert finding.evidence["metrics"]["occurrences"] == 3


def test_exact_repetition_is_suppressed_when_progress_is_reported():
    events = [make_event(i, status="success", progress=True) for i in range(5)]
    assert detect_exact_repetition(events, DetectionSettings()) == []


def test_exact_repetition_without_progress_or_failure_is_not_escalated():
    events = [make_event(i, status="success", progress=None) for i in range(5)]
    assert detect_exact_repetition(events, DetectionSettings()) == []


def test_different_tools_with_same_arguments_are_not_identical():
    events = [make_event(i, tool=f"tool_{i}", status="failure", progress=False) for i in range(4)]
    assert detect_exact_repetition(events, DetectionSettings()) == []


def test_semantic_repetition_detects_near_duplicates():
    variants = [
        {"query": "Database Timeout"},
        {"query": "database   timeout"},
        {"query": "DATABASE TIMEOUT"},
        {"query": "database timeout "},
    ]
    events = [
        make_event(i, args=variant, status="failure" if i == 0 else "success", progress=False)
        for i, variant in enumerate(variants)
    ]
    findings = detect_semantic_repetition(events, DetectionSettings())
    assert len(findings) == 1
    assert findings[0].category == "semantic_repetition"
    assert len(findings[0].evidence["event_ids"]) == 4


def test_oscillation_detects_alternating_failures():
    events = []
    for index in range(6):
        tool = "edit_file" if index % 2 == 0 else "run_tests"
        events.append(
            make_event(
                index,
                tool=tool,
                args={"attempt": index, "path": "db.py"},
                status="failure",
                error="syntax_error" if tool == "edit_file" else "test_failure",
                progress=False,
            )
        )
    findings = detect_oscillation(events, DetectionSettings())
    assert len(findings) == 1
    assert findings[0].category == "oscillation"
    assert findings[0].evidence["metrics"]["cycles"] >= 2
    assert "edit_file" in findings[0].explanation


def test_oscillation_requires_failure_or_no_progress_evidence():
    events = []
    for index in range(6):
        events.append(
            make_event(
                index,
                tool="edit_file" if index % 2 == 0 else "run_tests",
                args={"attempt": index},
                status="success",
                progress=True,
            )
        )
    assert detect_oscillation(events, DetectionSettings()) == []


def test_repeated_failures_triggers_at_threshold():
    events = [
        make_event(i, tool="call_api", args={"attempt": i}, status="failure", error="rate_limit")
        for i in range(3)
    ]
    findings = detect_repeated_failures(events, DetectionSettings())
    assert len(findings) == 1
    assert findings[0].evidence["metrics"]["failures"] == 3
    assert findings[0].confidence >= 0.8


def test_repeated_failures_below_threshold_does_not_trigger():
    events = [
        make_event(i, tool="call_api", status="failure", error="rate_limit") for i in range(2)
    ]
    assert detect_repeated_failures(events, DetectionSettings()) == []


def test_no_progress_requires_explicit_progress_signals():
    events = [make_event(i, status="success", progress=None) for i in range(10)]
    assert detect_no_progress(events, DetectionSettings()) == []


def test_no_progress_triggers_on_explicit_false_signals():
    events = [make_event(i, status="success", progress=False) for i in range(8)]
    findings = detect_no_progress(events, DetectionSettings())
    assert len(findings) == 1
    assert findings[0].evidence["metrics"]["true_progress_signals"] == 0


def test_missing_event_data_does_not_crash_detectors():
    events = [
        Event(
            id="broken",
            agent_id="a",
            session_id="s",
            timestamp=BASE,
            tool_name="tool",
            status="unknown",
            normalized_input_hash="",
            semantic_hash="",
            progress=None,
            sanitized_input=None,
            error_category=None,
        )
    ]
    assert detect_all(events, DetectionSettings()) == []


def test_out_of_order_events_are_sorted_safely():
    events = [
        make_event(2, status="failure", progress=False),
        make_event(0, status="failure", progress=False),
        make_event(1, status="failure", progress=False),
    ]
    findings = detect_exact_repetition(events, DetectionSettings())
    assert findings[0].evidence["event_ids"] == ["evt-0", "evt-1", "evt-2"]
    assert findings[0].first_seen_at < findings[0].last_seen_at


def test_budget_detection_triggers_and_respects_boundaries():
    settings = DetectionSettings()
    events = [make_event(i, progress=True) for i in range(5)]
    session = Session(
        id="session-1",
        agent_id="agent-1",
        status="active",
        started_at=BASE,
        event_count=settings.budget.max_tool_calls + 1,
    )
    findings = detect_budget(events, settings, session)
    assert len(findings) == 1
    assert findings[0].category == "budget_exceeded"
    assert findings[0].risk_score <= 100

    below = Session(
        id="session-1",
        agent_id="agent-1",
        status="active",
        started_at=BASE,
        event_count=2,
    )
    assert detect_budget(events, settings, below) == []


def test_severity_mapping_is_monotonic():
    severities = [severity_for(score) for score in (0, 10, 20, 40, 65, 85, 100)]
    assert severities == ["INFO", "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", "CRITICAL"]


def test_all_finding_risks_stay_in_range():
    events = []
    for index in range(12):
        events.append(
            make_event(
                index,
                tool="edit_file" if index % 2 == 0 else "run_tests",
                args={"attempt": index},
                status="failure",
                error="boom",
                progress=False,
                session="session-1",
            )
        )
    session = Session(
        id="session-1",
        agent_id="agent-1",
        status="active",
        started_at=BASE,
        event_count=12,
    )
    findings = detect_all(events, DetectionSettings(), session)
    assert findings
    for finding in findings:
        assert 0 <= finding.risk_score <= 100
        assert 0 <= finding.confidence <= 1
        assert finding.evidence["event_ids"]
        assert set(finding.evidence["event_ids"]).issubset({event.id for event in events})
