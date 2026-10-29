"""Database engine, session lifecycle, and schema bootstrap."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        # Ensure the parent directory exists for file-backed SQLite databases.
        prefix = "sqlite:///"
        if url.startswith(prefix):
            raw_path = url[len(prefix) :]
            if raw_path and not raw_path.startswith(":memory:"):
                Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False}
    return create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )


engine = _make_engine()


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover - driver hook
    if engine.url.get_backend_name() == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database() -> None:
    """Create tables for local development when no migrations were run.

    Production deployments should run ``alembic upgrade head`` and set
    ``DEADLOOP_AUTO_CREATE=0``. The Alembic migration mirrors these models.
    """
    import app.models  # noqa: F401  (register metadata)

    Base.metadata.create_all(bind=engine)


def reset_database_for_tests() -> None:
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
