"""Payload sanitization.

Agent input/output is untrusted and may contain credentials. Only sanitized
representations are persisted. This module never logs input values.
"""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|secret|"
    r"password|passwd|authorization|cookie|credential|private[_-]?key|client[_-]?secret|"
    r"session[_-]?id|database[_-]?url|connection[_-]?string)"
)
SECRET_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bdl_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(password|passwd|token|secret)\s*[=:]\s*\S+"),
]
MAX_STRING_LENGTH = 2000
MAX_DEPTH = 7
MAX_ITEMS = 100
TRUNCATION_MARKER = "…[truncated]"


class RedactionPolicy:
    def __init__(self, enabled: bool = True, extra_keys: list[str] | None = None):
        self.enabled = enabled
        self.extra_keys = {k.lower() for k in (extra_keys or []) if k}

    def _is_sensitive_key(self, key: str) -> bool:
        lowered = key.lower()
        return lowered in self.extra_keys or bool(SENSITIVE_KEY_RE.search(lowered))

    def _sanitize_string(self, value: str) -> str:
        if not self.enabled:
            return value[:MAX_STRING_LENGTH]
        for pattern in SECRET_VALUE_PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value[:MAX_STRING_LENGTH]

    def sanitize(self, value: Any, depth: int = 0) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self._sanitize_string(value)
        if depth >= MAX_DEPTH:
            return "[MAX_DEPTH]"
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= MAX_ITEMS:
                    result["_truncated"] = True
                    break
                key_text = str(key)[:200]
                if self.enabled and self._is_sensitive_key(key_text):
                    result[key_text] = "[REDACTED]"
                else:
                    result[key_text] = self.sanitize(item, depth + 1)
            return result
        if isinstance(value, (list, tuple, set)):
            return [self.sanitize(item, depth + 1) for item in list(value)[:MAX_ITEMS]]
        return self._sanitize_string(str(value))


def sanitize(value: Any, policy: RedactionPolicy | None = None) -> Any:
    return (policy or RedactionPolicy()).sanitize(value)


def truncate_text(value: str, limit: int = 1000) -> str:
    return value[:limit] + (TRUNCATION_MARKER if len(value) > limit else "")


__all__ = ["RedactionPolicy", "SENSITIVE_KEY_RE", "sanitize", "truncate_text"]
