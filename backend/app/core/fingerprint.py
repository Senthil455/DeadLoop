"""Stable event fingerprints and argument normalization."""

from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from typing import Any

VOLATILE_KEYS = {
    "timestamp",
    "time",
    "ts",
    "request_id",
    "requestid",
    "trace_id",
    "traceid",
    "span_id",
    "nonce",
    "idempotency_key",
    "created_at",
}
WHITESPACE_RE = re.compile(r"\s+")


def _normalize(value: Any, *, lowercase: bool, drop_volatile: bool = True) -> Any:
    if isinstance(value, str):
        collapsed = WHITESPACE_RE.sub(" ", value).strip()
        return collapsed.lower() if lowercase else collapsed
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            key_text = str(key)
            if drop_volatile and key_text.lower() in VOLATILE_KEYS:
                continue
            items.append((key_text, _normalize(item, lowercase=lowercase, drop_volatile=drop_volatile)))
        return {key: item for key, item in sorted(items, key=lambda pair: pair[0])}
    if isinstance(value, (list, tuple)):
        return [_normalize(item, lowercase=lowercase, drop_volatile=drop_volatile) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical_json(value: Any, *, lowercase: bool = False) -> str:
    normalized = _normalize(value, lowercase=lowercase)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def fingerprint(value: Any, *, lowercase: bool = False) -> str:
    return hashlib.sha256(canonical_json(value, lowercase=lowercase).encode("utf-8")).hexdigest()


def semantic_similarity(left: Any, right: Any) -> float:
    """Similarity of two normalized argument payloads in [0, 1]."""
    a = canonical_json(left, lowercase=True)
    b = canonical_json(right, lowercase=True)
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


__all__ = [
    "canonical_json",
    "fingerprint",
    "semantic_similarity",
]
