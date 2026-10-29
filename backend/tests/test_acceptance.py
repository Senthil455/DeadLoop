"""Acceptance scenarios and evidence-integrity tests."""

from __future__ import annotations

from tests.conftest import ingest, sample_event


def _session_incidents(client, headers, session_id):
    return [
        incident
        for incident in client.get("/api/v1/incidents?limit=200", headers=headers).json()
        if incident["session_id"] == session_id
    ]


def test_healthy_agent_does_not_create_high_severity_incident(client, admin_headers):
    response = client.post("/api/v1/demo/scenarios/healthy", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    incidents = _session_incidents(client, admin_headers, body["session_id"])
    assert not [i for i in incidents if i["severity"] in {"HIGH", "CRITICAL"}]
    session = client.get(f"/api/v1/sessions/{body['session_id']}", headers=admin_headers).json()
    assert session["event_count"] == 9
    assert len(session["events"]) == 9
    assert all(event["status"] == "success" for event in session["events"])


def test_exact_repetition_scenario_persists_events_and_detection(client, admin_headers):
    response = client.post("/api/v1/demo/scenarios/exact_repetition", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["events_created"] == 4
    assert "exact_repetition" in body["detections"]
    incidents = _session_incidents(client, admin_headers, body["session_id"])
    repetition = next(i for i in incidents if i["detection_category"] == "exact_repetition")
    detail = client.get(
        f"/api/v1/incidents/{repetition['id']}", headers=admin_headers
    ).json()
    evidence_ids = detail["detection"]["evidence"]["event_ids"]
    assert len(evidence_ids) == 4
    session = client.get(f"/api/v1/sessions/{body['session_id']}", headers=admin_headers).json()
    persisted_ids = {event["id"] for event in session["events"]}
    assert set(evidence_ids).issubset(persisted_ids)
    assert detail["detection"]["evidence"]["metrics"]["occurrences"] == 4
    assert detail["detection"]["risk_score"] == detail["risk_score"]
    assert "not a probability" in detail["detection"]["explanation"]


def test_oscillation_scenario_creates_oscillation_finding(client, admin_headers):
    response = client.post("/api/v1/demo/scenarios/oscillation", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert "oscillation" in body["detections"]
    incidents = _session_incidents(client, admin_headers, body["session_id"])
    oscillation = next(i for i in incidents if i["detection_category"] == "oscillation")
    detail = client.get(f"/api/v1/incidents/{oscillation['id']}", headers=admin_headers).json()
    assert detail["detection"]["evidence"]["metrics"]["cycles"] >= 2
    assert detail["detection"]["evidence"]["event_ids"]


def test_repeated_failure_scenario_creates_failure_finding(client, admin_headers):
    response = client.post("/api/v1/demo/scenarios/repeated_failure", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert "repeated_failure" in body["detections"]
    incidents = _session_incidents(client, admin_headers, body["session_id"])
    failure = next(i for i in incidents if i["detection_category"] == "repeated_failure")
    detail = client.get(f"/api/v1/incidents/{failure['id']}", headers=admin_headers).json()
    assert detail["detection"]["evidence"]["metrics"]["failures"] == 7


def test_ambiguous_repetition_is_not_escalated(client, admin_headers):
    response = client.post("/api/v1/demo/scenarios/ambiguous", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    incidents = _session_incidents(client, admin_headers, body["session_id"])
    assert incidents == []
    assert body["detections"] == []


def test_full_acceptance_workflow_ingestion_to_intervention(client, admin_headers, set_mode):
    """The primary acceptance scenario, exercised through the public API."""
    set_mode("approval_required")
    # 1. Start from a clean dashboard.
    assert client.get("/api/v1/incidents", headers=admin_headers).json() == []

    # 2. Run the exact-repetition scenario through real ingestion/detection.
    scenario = client.post(
        "/api/v1/demo/scenarios/exact_repetition", headers=admin_headers
    ).json()
    assert scenario["events_created"] == 4

    # 3. The dashboard reflects activity and incidents.
    overview = client.get("/api/v1/stats/overview", headers=admin_headers).json()
    assert overview["total_agents"] == 1
    assert overview["open_incidents"] >= 1
    assert overview["demo_mode"] is True
    assert sum(point["events"] for point in overview["event_series"]) >= 4

    # 4. Inspect the incident and its evidence.
    incidents = _session_incidents(client, admin_headers, scenario["session_id"])
    repetition = next(i for i in incidents if i["detection_category"] == "exact_repetition")
    detail = client.get(f"/api/v1/incidents/{repetition['id']}", headers=admin_headers).json()
    evidence_ids = detail["detection"]["evidence"]["event_ids"]
    session = client.get(
        f"/api/v1/sessions/{scenario['session_id']}", headers=admin_headers
    ).json()
    events_by_id = {event["id"]: event for event in session["events"]}
    for evidence_id in evidence_ids:
        assert evidence_id in events_by_id
        assert events_by_id[evidence_id]["status"] == "failure"

    # 5. Acknowledge.
    acknowledged = client.post(
        f"/api/v1/incidents/{repetition['id']}/status",
        json={"status": "ACKNOWLEDGED", "note": "Confirmed loop."},
        headers=admin_headers,
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"

    # 6. Request and approve a pause; the simulator must acknowledge.
    intervention = client.post(
        f"/api/v1/incidents/{repetition['id']}/interventions",
        json={"action": "pause"},
        headers=admin_headers,
    ).json()
    assert intervention["approval_status"] == "PENDING"
    approved = client.post(
        f"/api/v1/interventions/{intervention['id']}/approve",
        headers=admin_headers,
    ).json()
    assert approved["execution_status"] == "ACKNOWLEDGED"
    assert approved["simulated"] is True
    assert approved["result"]["acknowledged"] is True

    # 7. Resolve and verify persistence across a new request/session.
    resolved = client.post(
        f"/api/v1/incidents/{repetition['id']}/status",
        json={"status": "RESOLVED", "note": "Paused and reviewed."},
        headers=admin_headers,
    )
    assert resolved.status_code == 200
    reloaded = client.get(f"/api/v1/incidents/{repetition['id']}", headers=admin_headers).json()
    assert reloaded["status"] == "RESOLVED"
    assert any(i["execution_status"] == "ACKNOWLEDGED" for i in reloaded["interventions"])
    audit_actions = [entry["action"] for entry in reloaded["audit"]]
    assert "incident.created" in audit_actions
    assert "incident.acknowledged" in audit_actions
    assert "intervention.executed" in audit_actions
    assert "incident.resolved" in audit_actions
    paused_session = client.get(
        f"/api/v1/sessions/{scenario['session_id']}", headers=admin_headers
    ).json()
    assert paused_session["status"] == "paused"


def test_stats_endpoint_metrics_are_database_backed(client, admin_headers):
    ingest(
        client,
        [
            sample_event(
                event_id="stat-1",
                status="failure",
                error_category="timeout",
                progress={"made_progress": False},
            ),
            sample_event(event_id="stat-2", tool_name="read_file", input={"path": "x"}),
        ],
        admin_headers,
    )
    stats = client.get("/api/v1/stats/overview", headers=admin_headers).json()
    assert stats["total_agents"] == 1
    assert stats["failed_tool_calls"] == 1
    assert stats["active_sessions"] == 1
    assert len(stats["event_series"]) == 24
    assert len(stats["recent_activity"]) == 1
