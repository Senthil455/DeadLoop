"""Migration verification against a clean SQLite database."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "agents",
    "api_keys",
    "audit_logs",
    "detections",
    "events",
    "incident_notes",
    "incidents",
    "interventions",
    "sessions",
    "settings",
    "alembic_version",
}


def _run_alembic(database: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DEADLOOP_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["PYTHONPATH"] = str(BACKEND_DIR)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_clean_database_migration_upgrade_and_downgrade(tmp_path):
    database = tmp_path / "migrated.db"
    result = _run_alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert EXPECTED_TABLES.issubset(tables)
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert revision and len(revision[0]) == 12
        foreign_keys = connection.execute("PRAGMA foreign_key_list(incidents)").fetchall()
        assert foreign_keys

    downgrade = _run_alembic(database, "downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "incidents" not in tables
        assert "events" not in tables
