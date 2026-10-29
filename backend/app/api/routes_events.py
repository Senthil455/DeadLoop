"""Event ingestion routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from ..config import get_settings
from ..core.security import require_ingest_auth
from ..database import get_db
from ..schemas import EventBatchIn, EventIn, IngestResult
from ..services.ingestion import ingest_payloads

router = APIRouter(prefix="/api/v1", tags=["events"])


def _commit_ingestion(db: DbSession, result: dict) -> IngestResult:
    if not result["accepted"] and result["rejected"]:
        # Nothing persisted; surface a useful validation response.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "No events were accepted.", "rejected": result["rejected"]},
        )
    db.commit()
    return IngestResult(**result)


@router.post("/events", response_model=IngestResult, status_code=status.HTTP_202_ACCEPTED)
def ingest_event(
    payload: EventIn,
    db: DbSession = Depends(get_db),
    _actor: str = Depends(require_ingest_auth),
):
    return _commit_ingestion(db, ingest_payloads(db, [payload]))


@router.post("/events/batch", response_model=IngestResult, status_code=status.HTTP_202_ACCEPTED)
def ingest_batch(
    payload: EventBatchIn,
    db: DbSession = Depends(get_db),
    _actor: str = Depends(require_ingest_auth),
):
    maximum = get_settings().max_batch_size
    if len(payload.events) > maximum:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Batch exceeds the configured maximum of {maximum} events.",
        )
    return _commit_ingestion(db, ingest_payloads(db, payload.events))
