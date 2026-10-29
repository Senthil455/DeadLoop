"""API, authorization, validation, redaction, and persistence tests."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiKey, Event, Incident
from tests.conftest import ingest, sample_event


def test_health_is_public_and_does_not_leak_secrets(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "admin_token" not in json.dumps(body).lower()
    assert body["database"] == "ok"


def test_admin_endpoints_require_valid_token(client):
    assert client.get("/api/v1/agents").status_code == 401
    assert client.get("/api/v1/agents", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert (
        client.get("/api/v1/agents", headers={"X-Admin-Token": "test-admin-token"}).status_code
        == 200
    )


def test_ingestion_requires_authentication(client):
    response = ingest(client, [sample_event()])
    assert response.status_code == 401


def test_valid_ingestion_persists_events_and_agents(client, admin_headers):
    response = ingest(client, [sample_event()], admin_headers)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted"] == 1
    assert body["duplicates"] == 0
    agents = client.get("/api/v1/agents", headers=admin_headers).json()
    assert len(agents) == 1
    assert agents[0]["id"] == "agent-1"
    assert agents[0]["event_count"] == 1
    sessions = client.get("/api/v1/sessions", headers=admin_headers).json()
    assert sessions[0]["id"] == "session-1"
    assert sessions[0]["event_count"] == 1


def test_invalid_payload_is_rejected_with_useful_error(client, admin_headers):
    response = ingest(client, [{"agent_id": "a", "session_id": "s"}], admin_headers)
    assert response.status_code == 422
    assert "tool_name" in response.text


def test_oversized_request_is_rejected(client, admin_headers):
    event = sample_event(input={"blob": "x" * 300_000})
    response = client.post("/api/v1/events", json=event, headers=admin_headers)
    assert response.status_code == 413


def test_batch_size_limit_is_enforced(client, admin_headers, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DEADLOOP_MAX_BATCH_SIZE", "2")
    get_settings.cache_clear()
    try:
        response = ingest(
            client, [sample_event(event_id=str(i)) for i in range(3)], admin_headers
        )
        assert response.status_code == 413
    finally:
        get_settings.cache_clear()


def test_duplicate_event_ingestion_is_idempotent(client, admin_headers):
    events = [
        sample_event(
            event_id=f"dupe-{index}",
            status="failure",
            error_category="timeout",
            progress={"made_progress": False},
        )
        for index in range(4)
    ]
    first = ingest(client, events, admin_headers)
    assert first.status_code == 202
    assert first.json()["accepted"] == 4
    incidents_before = client.get("/api/v1/incidents", headers=admin_headers).json()
    assert len(incidents_before) >= 1

    duplicate = ingest(client, events, admin_headers)
    assert duplicate.status_code == 202
    assert duplicate.json()["accepted"] == 0
    assert duplicate.json()["duplicates"] == 4
    incidents_after = client.get("/api/v1/incidents", headers=admin_headers).json()
    assert len(incidents_after) == len(incidents_before)

    db = SessionLocal()
    try:
        assert len(db.execute(select(Event)).scalars().all()) == 4
    finally:
        db.close()


def test_session_agent_mismatch_is_rejected_without_losing_valid_events(client, admin_headers):
    events = [
        sample_event(event_id="valid-1", agent_id="agent-a", session_id="shared"),
        sample_event(event_id="conflict", agent_id="agent-b", session_id="shared"),
        sample_event(event_id="valid-2", agent_id="agent-a", session_id="shared"),
    ]
    response = ingest(client, events, admin_headers)
    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 2
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["index"] == 1
    db = SessionLocal()
    try:
        assert len(db.execute(select(Event)).scalars().all()) == 2
    finally:
        db.close()


def test_api_keys_are_hashed_and_write_only(client, admin_headers):
    created = client.post("/api/v1/api-keys", json={"name": "sdk"}, headers=admin_headers)
    assert created.status_code == 201
    raw = created.json()["api_key"]
    assert raw.startswith("dl_")

    listed = client.get("/api/v1/api-keys", headers=admin_headers)
    assert listed.status_code == 200
    assert "api_key" not in listed.text
    assert raw not in listed.text

    db = SessionLocal()
    try:
        record = db.execute(select(ApiKey)).scalars().one()
        assert record.key_hash != raw
        assert len(record.key_hash) == 64
    finally:
        db.close()

    event = sample_event(event_id="keyed")
    assert ingest(client, [event], {"X-API-Key": raw}).status_code == 202
    assert client.get("/api/v1/agents", headers={"X-API-Key": raw}).status_code == 401

    key_id = created.json()["id"]
    assert client.delete(f"/api/v1/api-keys/{key_id}", headers=admin_headers).status_code == 200
    assert ingest(client, [sample_event(event_id="keyed-2")], {"X-API-Key": raw}).status_code == 401


def test_sensitive_payloads_are_redacted_before_storage_and_response(client, admin_headers):
    secret = "sk-super-secret-value-1234567890"
    event = sample_event(
        event_id="redact-1",
        input={
            "api_key": secret,
            "nested": {"password": "hunter2", "authorization": "Bearer abcdefghijklmnop"},
            "query": "safe",
        },
        output={"note": f"using Bearer {secret}"},
        metadata={"access_token": "abc123", "region": "eu"},
    )
    assert ingest(client, [event], admin_headers).status_code == 202
    detail = client.get("/api/v1/sessions/session-1", headers=admin_headers)
    text = detail.text
    assert secret not in text
    assert "hunter2" not in text
    assert "[REDACTED]" in text
    stored = detail.json()["events"][0]
    assert stored["sanitized_input"]["query"] == "safe"
    assert stored["sanitized_input"]["nested"]["password"] == "[REDACTED]"


def test_event_filters_and_pagination(client, admin_headers):
    events = [
        sample_event(event_id=f"p-{i}", tool_name="tool_a" if i % 2 == 0 else "tool_b", status="failure" if i == 3 else "success")
        for i in range(12)
    ]
    assert ingest(client, events, admin_headers).status_code == 202
    page = client.get(
        "/api/v1/sessions/session-1?page=2&page_size=5&order=asc", headers=admin_headers
    )
    assert page.status_code == 200
    body = page.json()
    assert body["total_events"] == 12
    assert body["pages"] == 3
    assert len(body["events"]) == 5
    assert body["events"][0]["tool_name"] == "tool_b"
    filtered = client.get(
        "/api/v1/sessions/session-1?tool=tool_b&status=success", headers=admin_headers
    ).json()
    assert filtered["total_events"] == 5
    assert all(event["tool_name"] == "tool_b" for event in filtered["events"])
    searched = client.get(
        "/api/v1/sessions/session-1?q=tool_a", headers=admin_headers
    ).json()
    assert searched["total_events"] == 6


def test_security_headers_and_cors(client):
    allowed = client.get(
        "/api/v1/health", headers={"Origin": "http://localhost:5173"}
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert allowed.headers["x-content-type-options"] == "nosniff"
    assert allowed.headers["x-frame-options"] == "DENY"
    disallowed = client.get(
        "/api/v1/health", headers={"Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in disallowed.headers


def test_unknown_resources_return_404(client, admin_headers):
    assert client.get("/api/v1/incidents/missing", headers=admin_headers).status_code == 404
    assert client.get("/api/v1/sessions/missing", headers=admin_headers).status_code == 404
    assert client.get("/api/v1/agents/missing", headers=admin_headers).status_code == 404
    assert (
        client.post("/api/v1/demo/scenarios/unknown", headers=admin_headers).status_code == 404
    )


def test_incident_status_note_audit_and_history(client, admin_headers):
    events = [
        sample_event(
            event_id=f"incident-{i}",
            status="failure",
            error_category="timeout",
            progress={"made_progress": False},
        )
        for i in range(4)
    ]
    ingest(client, events, admin_headers)
    incidents = client.get("/api/v1/incidents", headers=admin_headers).json()
    assert incidents
    incident = incidents[0]
    incident_id = incident["id"]

    note = client.post(
        f"/api/v1/incidents/{incident_id}/notes",
        json={"body": "Investigating the repeated timeout."},
        headers=admin_headers,
    )
    assert note.status_code == 200
    assert note.json()["notes"][0]["body"] == "Investigating the repeated timeout."

    acknowledged = client.post(
        f"/api/v1/incidents/{incident_id}/status",
        json={"status": "ACKNOWLEDGED"},
        headers=admin_headers,
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"
    assert any(entry["action"] == "incident.acknowledged" for entry in acknowledged.json()["audit"])

    dismissed = client.post(
        f"/api/v1/incidents/{incident_id}/status",
        json={"status": "DISMISSED", "note": "False positive after review."},
        headers=admin_headers,
    )
    assert dismissed.status_code == 200
    listed = client.get("/api/v1/incidents?status=DISMISSED", headers=admin_headers).json()
    assert any(item["id"] == incident_id for item in listed)

    assert (
        client.post(
            f"/api/v1/incidents/{incident_id}/status",
            json={"status": "RESOLVED"},
            headers=admin_headers,
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/incidents/{incident_id}/notes",
            json={"body": ""},
            headers=admin_headers,
        ).status_code
        == 422
    )


def test_agent_patch_and_per_agent_config_validation(client, admin_headers):
    ingest(client, [sample_event()], admin_headers)
    patched = client.patch(
        "/api/v1/agents/agent-1",
        json={"name": "Renamed", "description": "Updated", "framework": "custom"},
        headers=admin_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"
    invalid = client.patch(
        "/api/v1/agents/agent-1",
        json={"configuration": {"detection": {"exact_repetition": {"min_occurrences": 999}}}},
        headers=admin_headers,
    )
    assert invalid.status_code == 422


def test_detection_settings_validation_and_persistence(client, admin_headers):
    current = client.get("/api/v1/settings/detection", headers=admin_headers)
    assert current.status_code == 200
    payload = current.json()
    payload["exact_repetition"]["min_occurrences"] = 4
    updated = client.put("/api/v1/settings/detection", json=payload, headers=admin_headers)
    assert updated.status_code == 200
    assert (
        client.get("/api/v1/settings/detection", headers=admin_headers).json()["exact_repetition"][
            "min_occurrences"
        ]
        == 4
    )
    payload["exact_repetition"]["min_occurrences"] = 1
    assert (
        client.put("/api/v1/settings/detection", json=payload, headers=admin_headers).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/settings/detection",
            json={"unknown_section": {"min_occurrences": 3}},
            headers=admin_headers,
        ).status_code
        == 422
    )


def test_general_settings_do_not_expose_secrets(client, admin_headers, monkeypatch):
    monkeypatch.setenv("DEADLOOP_AI_API_KEY", "secret-ai-key")
    response = client.get("/api/v1/settings", headers=admin_headers)
    assert response.status_code == 200
    assert "secret-ai-key" not in response.text
    assert response.json()["ai_api_key_configured"] is True
    assert "ai_api_key" not in response.json()


def test_demo_reset_requires_confirmation_and_isolates_demo_data(client, admin_headers):
    assert (
        client.post("/api/v1/demo/reset", json={"confirm": False}, headers=admin_headers).status_code
        == 400
    )
    ingest(client, [sample_event(agent_id="real-agent")], admin_headers)
    demo = client.post("/api/v1/demo/scenarios/exact_repetition", headers=admin_headers)
    assert demo.status_code == 200
    reset = client.post("/api/v1/demo/reset", json={"confirm": True}, headers=admin_headers)
    assert reset.status_code == 200
    agents = client.get("/api/v1/agents", headers=admin_headers).json()
    assert [agent["id"] for agent in agents] == ["real-agent"]
