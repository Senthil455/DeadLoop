"""Buffer agent tool calls and submit them to DEADLOOP's ingestion API.

The SDK uses only the Python standard library. It never logs or prints payloads
and redacts credential-shaped fields by default.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

REDACTED = "[REDACTED]"
SENSITIVE_KEY = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|passwd|"
    r"secret|cookie|credential|private[_-]?key|client[_-]?secret)"
)
SECRET_VALUE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
MAX_BUFFER = 1000

Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class DeadloopError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[MAX_DEPTH]"
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:100]:
            key_text = str(key)
            if SENSITIVE_KEY.search(key_text.lower()):
                result[key_text] = REDACTED
            else:
                result[key_text] = _redact(item, depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_redact(item, depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        return SECRET_VALUE.sub(REDACTED, value)[:2000]
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_transport(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise DeadloopError(
            f"DEADLOOP ingestion failed with HTTP {exc.code}: {detail}", exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise DeadloopError(f"DEADLOOP ingestion unavailable: {exc.reason}") from exc


@dataclass
class Event:
    tool_name: str
    action: str | None = None
    input: Any = None
    output: Any = None
    status: str = "success"
    error_category: str | None = None
    duration_ms: int | None = None
    retry_count: int = 0
    tokens: int | None = None
    cost_usd: float | None = None
    progress: bool | None = None
    metadata: dict[str, Any] | None = None
    task: str | None = None
    model: str | None = None

    def to_payload(self, agent_id: str, session_id: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_id": uuid.uuid4().hex,
            "agent_id": agent_id,
            "session_id": session_id,
            "timestamp": _utc_now(),
            "tool_name": self.tool_name,
            "action": self.action,
            "input": _redact(self.input),
            "output": _redact(self.output),
            "status": self.status if self.status in {"success", "failure", "unknown"} else "unknown",
            "error_category": self.error_category,
            "duration_ms": self.duration_ms,
            "retry_count": max(0, self.retry_count),
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
            "task": self.task,
            "model": self.model,
            "metadata": _redact(self.metadata) if self.metadata is not None else None,
        }
        if self.progress is not None:
            payload["progress"] = {"made_progress": bool(self.progress)}
        return payload


class DeadloopClient:
    """Thread-safe buffered client.

    Example:
        with DeadloopClient(api_key=key, agent_id="support-agent") as client:
            client.emit("search_web", input={"query": q}, progress=True)
            with client.session():
                ...
    """

    def __init__(
        self,
        *,
        api_key: str,
        agent_id: str,
        endpoint: str = "http://127.0.0.1:8000",
        session_id: str | None = None,
        batch_size: int = 20,
        timeout: float = 5.0,
        auto_flush_seconds: float = 2.0,
        enabled: bool = True,
        transport: Transport | None = None,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        if not agent_id:
            raise ValueError("agent_id is required")
        self.api_key = api_key
        self.agent_id = agent_id
        self.session_id = session_id or uuid.uuid4().hex
        self.batch_size = max(1, min(batch_size, 100))
        self.timeout = max(0.5, timeout)
        self.auto_flush_seconds = max(0.0, auto_flush_seconds)
        self.enabled = enabled
        self._transport = transport or _default_transport
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._last_flush = time.monotonic()
        self.endpoint = self._normalize_endpoint(endpoint)

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        endpoint = endpoint.rstrip("/")
        if endpoint.endswith("/api/v1/events"):
            return endpoint + "/batch"
        if endpoint.endswith("/api/v1/events/batch"):
            return endpoint
        if endpoint.endswith("/api/v1"):
            return endpoint + "/events/batch"
        return endpoint + "/api/v1/events/batch"

    def _maybe_auto_flush(self) -> None:
        if (
            self.auto_flush_seconds
            and len(self._buffer) < self.batch_size
            and time.monotonic() - self._last_flush >= self.auto_flush_seconds
        ):
            self.flush()

    def emit(self, tool_name: str, **kwargs: Any) -> str:
        """Queue one event. Returns the event ID."""
        event = Event(tool_name=tool_name, **kwargs)
        payload = event.to_payload(self.agent_id, self.session_id)
        if not self.enabled:
            return payload["event_id"]
        with self._lock:
            self._buffer.append(payload)
            if len(self._buffer) > MAX_BUFFER:
                self._buffer = self._buffer[-MAX_BUFFER:]
            should_flush = len(self._buffer) >= self.batch_size
        if should_flush:
            self.flush()
        else:
            self._maybe_auto_flush()
        return payload["event_id"]

    event = emit

    def flush(self) -> dict[str, Any]:
        if not self.enabled:
            return {"accepted": 0, "duplicates": 0, "disabled": True}
        with self._lock:
            if not self._buffer:
                return {"accepted": 0, "duplicates": 0}
            batch = self._buffer[: self.batch_size]
            body = {"events": batch}
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": self.api_key,
                "User-Agent": "deadloop-python-sdk/0.1.0",
            }
            try:
                result = self._transport(self.endpoint, headers, body, self.timeout)
            except Exception:
                self._last_flush = time.monotonic()
                raise
            self._buffer = self._buffer[len(batch) :]
            self._last_flush = time.monotonic()
        if isinstance(result, dict) and result.get("rejected"):
            raise DeadloopError(f"DEADLOOP rejected {len(result['rejected'])} event(s).")
        return result

    def pending(self) -> int:
        with self._lock:
            return len(self._buffer)

    def session(self, session_id: str | None = None) -> "_SessionContext":
        return _SessionContext(self, session_id)

    def close(self) -> None:
        try:
            while self.pending():
                self.flush()
        finally:
            self.enabled = False

    def __enter__(self) -> "DeadloopClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


class _SessionContext:
    def __init__(self, client: DeadloopClient, session_id: str | None):
        self.client = client
        self.previous = client.session_id
        self.session_id = session_id or uuid.uuid4().hex

    def __enter__(self) -> str:
        self.client.session_id = self.session_id
        return self.session_id

    def __exit__(self, *args) -> None:
        try:
            self.client.flush()
        finally:
            self.client.session_id = self.previous


__all__ = ["DeadloopClient", "DeadloopError", "Event", "REDACTED"]
