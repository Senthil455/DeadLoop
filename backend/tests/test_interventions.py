"""Intervention policy, approval, runtime acknowledgement, and safety tests."""

from __future__ import annotations

from tests.conftest import ingest, sample_event


def _make_real_incident(client, headers, agent="real-agent", session="real-session"):
    events = [
        sample_event(
            event_id=f"{session}-{i}",
            agent_id=agent,
            session_id=session,
            status="failure",
            error_category="timeout",
            progress={"made_progress": False},
        )
        for i in range(4)
    ]
    response = ingest(client, events, headers)
    assert response.status_code == 202
    incidents = client.get(f"/api/v1/incidents?agent_id={agent}", headers=headers).json()
    assert incidents
    return incidents[0]


def test_intervention_requires_admin_authentication(client):
    incident = _make_real_incident(client, {"X-Admin-Token": "test-admin-token"})
    response = client.post(
        f"/api/v1/incidents/{incident['id']}/interventions", json={"action": "pause"}
    )
    assert response.status_code == 401
    response = client.post(
        f"/api/v1/interventions/anything/approve", headers={"X-Admin-Token": "test-admin-token"}
    )
    assert response.status_code == 404


def test_observe_mode_never_initiates_an_intervention(client, admin_headers, set_mode):
    set_mode("observe")
    incident = _make_real_incident(client, admin_headers, agent="observe-agent", session="observe-s")
    response = client.post(
        f"/api/v1/incidents/{incident['id']}/interventions",
        json={"action": "pause"},
        headers=admin_headers,
    )
    assert response.status_code == 409
    detail = client.get(f"/api/v1/incidents/{incident['id']}", headers=admin_headers).json()
    assert detail["interventions"] == []


def test_notify_mode_never_initiates_an_intervention(client, admin_headers, set_mode):
    set_mode("notify")
    incident = _make_real_incident(client, admin_headers, agent="notify-agent", session="notify-s")
    response = client.post(
        f"/api/v1/incidents/{incident['id']}/interventions",
        json={"action": "pause"},
        headers=admin_headers,
    )
    assert response.status_code == 409


def test_approval_required_mode_waits_for_approval(client, admin_headers, set_mode):
    set_mode("approval_required")
    incident = _make_real_incident(client, admin_headers, agent="approval-agent", session="approval-s")
    request = client.post(
        f"/api/v1/incidents/{incident['id']}/interventions",
        json={"action": "pause"},
        headers=admin_headers,
    )
    assert request.status_code == 200
    intervention = request.json()
    assert intervention["approval_status"] == "PENDING"
    assert intervention["execution_status"] == "PENDING_APPROVAL"
    assert intervention["completed_at"] is None

    wrong = client.post(
        f"/api/v1/interventions/{intervention['id']}/approve",
        headers={"X-Admin-Token": "wrong"},
    )
    assert wrong.status_code == 401

    approved = client.post(
        f"/api/v1/interventions/{intervention['id']}/approve",
        json={"note": "Approved for review"},
        headers=admin_headers,
    )
    assert approved.status_code == 200
    executed = approved.json()
    assert executed["approval_status"] == "APPROVED"
    # No compatible runtime is connected for a real agent: no false success.
    assert executed["execution_status"] == "UNSUPPORTED"
    assert executed["result"]["acknowledged"] is False
    session = client.get("/api/v1/sessions/approval-s", headers=admin_headers).json()
    assert session["status"] == "active"


def test_rejection_and_double_decision_are_safe(client, admin_headers, set_mode):
    set_mode("approval_required")
    incident = _make_real_incident(client, admin_headers, agent="reject-agent", session="reject-s")
    intervention = client.post(
        f"/api/v1/incidents/{incident['id']}/interventions",
        json={"action": "pause"},
        headers=admin_headers,
    ).json()
    rejected = client.post(
        f"/api/v1/interventions/{intervention['id']}/reject",
        json={"note": "Do not pause"},
        headers=admin_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["approval_status"] == "REJECTED"
    assert rejected.json()["execution_status"] == "NOT_EXECUTED"
    again = client.post(
        f"/api/v1/interventions/{intervention['id']}/approve",
        headers=admin_headers,
    )
    assert again.status_code == 409


def test_automatic_mode_still_requires_runtime_acknowledgement(client, admin_headers, set_mode):
    set_mode("automatic")
    incident = _make_real_incident(client, admin_headers, agent="auto-agent", session="auto-s")
    request = client.post(
        f"/api/v1/incidents/{incident['id']}/interventions",
        json={"action": "pause"},
        headers=admin_headers,
    )
    assert request.status_code == 200
    body = request.json()
    assert body["approval_status"] == "NOT_REQUIRED"
    assert body["execution_status"] == "UNSUPPORTED"
    assert body["result"]["acknowledged"] is False
    session = client.get("/api/v1/sessions/auto-s", headers=admin_headers).json()
    assert session["status"] == "active"


def test_simulated_runtime_acknowledges_and_is_labeled(client, admin_headers, set_mode):
    set_mode("approval_required")
    demo = client.post("/api/v1/demo/scenarios/recovery", headers=admin_headers)
    assert demo.status_code == 200
    body = demo.json()
    incidents = client.get(
        f"/api/v1/incidents?agent_id={body['agent_id']}", headers=admin_headers
    ).json()
    incident = next(item for item in incidents if item["detection_category"] == "exact_repetition")
    intervention = client.post(
        f"/api/v1/incidents/{incident['id']}/interventions",
        json={"action": "pause"},
        headers=admin_headers,
    ).json()
    assert intervention["approval_status"] == "PENDING"
    approved = client.post(
        f"/api/v1/interventions/{intervention['id']}/approve",
        headers=admin_headers,
    ).json()
    assert approved["approval_status"] == "APPROVED"
    assert approved["execution_status"] == "ACKNOWLEDGED"
    assert approved["simulated"] is True
    assert approved["result"]["acknowledged"] is True
    assert "Simulated" in approved["result"]["message"]
    session = client.get(f"/api/v1/sessions/{body['session_id']}", headers=admin_headers).json()
    assert session["status"] == "paused"
    detail = client.get(f"/api/v1/incidents/{incident['id']}", headers=admin_headers).json()
    actions = [entry["action"] for entry in detail["audit"]]
    assert "intervention.requested" in actions
    assert "intervention.approved" in actions
    assert "intervention.executed" in actions


def test_intervention_cannot_be_requested_for_closed_incident(client, admin_headers, set_mode):
    set_mode("approval_required")
    incident = _make_real_incident(client, admin_headers, agent="closed-agent", session="closed-s")
    client.post(
        f"/api/v1/incidents/{incident['id']}/status",
        json={"status": "RESOLVED"},
        headers=admin_headers,
    )
    response = client.post(
        f"/api/v1/incidents/{incident['id']}/interventions",
        json={"action": "pause"},
        headers=admin_headers,
    )
    assert response.status_code == 409
