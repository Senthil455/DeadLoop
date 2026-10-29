"""Tests for the dependency-free DEADLOOP SDK."""

from __future__ import annotations

import json

import pytest

from deadloop import DeadloopClient, DeadloopError


def make_client(**kwargs):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        return {"accepted": len(body["events"]), "duplicates": 0}

    client = DeadloopClient(
        api_key="dl_test_key_12345678901234567890",
        agent_id="agent-1",
        batch_size=3,
        auto_flush_seconds=0,
        transport=transport,
        **kwargs,
    )
    return client, calls


def test_endpoint_normalization():
    client, _ = make_client(endpoint="http://localhost:8000")
    assert client.endpoint == "http://localhost:8000/api/v1/events/batch"
    client, _ = make_client(endpoint="http://localhost:8000/api/v1")
    assert client.endpoint == "http://localhost:8000/api/v1/events/batch"
    client, _ = make_client(endpoint="http://localhost:8000/api/v1/events/batch")
    assert client.endpoint == "http://localhost:8000/api/v1/events/batch"


def test_batches_and_flushes_threshold():
    client, calls = make_client()
    for index in range(3):
        client.emit("search", input={"q": index}, progress=True)
    assert len(calls) == 1
    assert len(calls[0]["body"]["events"]) == 3
    assert calls[0]["headers"]["X-API-Key"].startswith("dl_")
    assert calls[0]["body"]["events"][0]["progress"] == {"made_progress": True}
    assert client.pending() == 0


def test_explicit_flush_and_event_id():
    client, calls = make_client()
    event_id = client.emit("read_file", input={"path": "x"}, status="success")
    assert client.pending() == 1
    result = client.flush()
    assert result["accepted"] == 1
    assert calls[0]["body"]["events"][0]["event_id"] == event_id
    assert client.pending() == 0


def test_credentials_are_redacted():
    client, calls = make_client()
    client.emit(
        "http_request",
        input={"api_key": "sk-abcdefghijklmnopqrstuv", "url": "https://example.test"},
        output={"header": "Bearer abcdefghijklmnopqrstuvwxyz"},
        metadata={"password": "hunter2"},
    )
    client.flush()
    payload = calls[0]["body"]["events"][0]
    assert payload["input"]["api_key"] == "[REDACTED]"
    assert "hunter2" not in json.dumps(payload)
    assert payload["output"]["header"] == "[REDACTED]"
    assert payload["metadata"]["password"] == "[REDACTED]"


def test_transport_failure_retains_events():
    def failing(url, headers, body, timeout):
        raise DeadloopError("connection refused")

    client = DeadloopClient(
        api_key="dl_test_key_12345678901234567890",
        agent_id="a",
        batch_size=10,
        auto_flush_seconds=0,
        transport=failing,
    )
    client.emit("tool")
    with pytest.raises(DeadloopError):
        client.flush()
    assert client.pending() == 1


def test_disabled_client_does_not_transmit():
    client, calls = make_client(enabled=False)
    client.emit("tool")
    client.flush()
    assert calls == []
    assert client.pending() == 0


def test_invalid_arguments():
    with pytest.raises(ValueError):
        DeadloopClient(api_key="", agent_id="a")
    with pytest.raises(ValueError):
        DeadloopClient(api_key="dl_x", agent_id="")


def test_session_context_restores_and_flushes():
    client, calls = make_client()
    original = client.session_id
    with client.session() as session_id:
        assert client.session_id == session_id
        client.emit("tool")
    assert client.session_id == original
    assert len(calls) == 1
    assert calls[0]["body"]["events"][0]["session_id"] == session_id
