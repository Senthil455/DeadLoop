"""Shared pytest fixtures. Environment is configured before importing the app."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix="deadloop-tests-"))
TEST_DB = TEST_DIR / "test.db"
os.environ["DEADLOOP_ENV"] = "test"
os.environ["DEADLOOP_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["DEADLOOP_ADMIN_TOKEN"] = "test-admin-token"
os.environ["DEADLOOP_AUTO_CREATE"] = "1"
os.environ.pop("DEADLOOP_AI_ENABLED", None)
os.environ.pop("DEADLOOP_AI_BASE_URL", None)
os.environ.pop("DEADLOOP_AI_MODEL", None)
os.environ.pop("DEADLOOP_AI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, reset_database_for_tests  # noqa: E402
from app.main import app  # noqa: E402
from app.services.settings import GeneralSettings, save_general_settings  # noqa: E402


@pytest.fixture()
def client():
    reset_database_for_tests()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers():
    return {"X-Admin-Token": "test-admin-token"}


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def ingest(client, events, headers=None):
    return client.post("/api/v1/events/batch", json={"events": events}, headers=headers or {})


def sample_event(**overrides):
    event = {
        "agent_id": "agent-1",
        "session_id": "session-1",
        "tool_name": "search_web",
        "action": "Search",
        "input": {"query": "database timeout"},
        "output": {"results": 0},
        "status": "success",
        "duration_ms": 42,
        "retry_count": 0,
        "progress": {"made_progress": True},
        "task": "Diagnose timeout",
    }
    event.update(overrides)
    return event


@pytest.fixture()
def api_key(client, admin_headers):
    response = client.post("/api/v1/api-keys", json={"name": "test key"}, headers=admin_headers)
    assert response.status_code == 201
    return response.json()["api_key"]


@pytest.fixture()
def set_mode(client, admin_headers):
    def _set(mode: str):
        response = client.put(
            "/api/v1/settings",
            json={"intervention_mode": mode},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _set
