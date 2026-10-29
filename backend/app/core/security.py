"""Authentication and credential helpers.

Two credential types exist:

* Admin token (``X-Admin-Token``) protects the dashboard and all state-changing
  operator actions. It is compared in constant time.
* Ingestion API keys (``X-API-Key``) are generated once, returned once, and
  stored as SHA-256 hashes. They only authorize event ingestion.
"""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import ApiKey, utcnow


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return "dl_" + secrets.token_urlsafe(32)


def admin_token_matches(candidate: str | None) -> bool:
    if not candidate:
        return False
    return secrets.compare_digest(candidate, get_settings().admin_token)


def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> str:
    if not admin_token_matches(x_admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid X-Admin-Token header is required.",
            headers={"WWW-Authenticate": "Token"},
        )
    return "admin"


def verify_api_key(raw_key: str, db: Session) -> ApiKey | None:
    if not raw_key.startswith("dl_") or len(raw_key) < 20:
        return None
    digest = hash_api_key(raw_key)
    record = db.execute(select(ApiKey).where(ApiKey.key_hash == digest)).scalar_one_or_none()
    if record is None or record.revoked_at is not None:
        return None
    record.last_used_at = utcnow()
    db.flush()
    return record


def require_ingest_auth(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
) -> str:
    """Admin tokens may ingest too (useful for local demos and tests)."""
    if admin_token_matches(x_admin_token):
        return "admin"
    if x_api_key and verify_api_key(x_api_key, db):
        return "api_key"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="An active ingestion API key or admin token is required.",
    )


def create_api_key_record(db: Session, name: str) -> tuple[str, ApiKey]:
    raw = generate_api_key()
    prefix = raw[:12]
    record = ApiKey(
        id=secrets.token_hex(16),
        name=name,
        prefix=prefix,
        key_hash=hash_api_key(raw),
    )
    db.add(record)
    db.flush()
    return raw, record


def revoke_api_key_record(db: Session, key_id: str) -> ApiKey | None:
    record = db.get(ApiKey, key_id)
    if record is None:
        return None
    if record.revoked_at is None:
        record.revoked_at = utcnow()
        db.flush()
    return record


__all__ = [
    "admin_token_matches",
    "create_api_key_record",
    "generate_api_key",
    "hash_api_key",
    "require_admin",
    "require_ingest_auth",
    "revoke_api_key_record",
    "verify_api_key",
]
