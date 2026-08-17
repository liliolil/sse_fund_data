"""JSONP response helpers."""

from __future__ import annotations

import json
import re
from typing import Any


_CALLBACK_RE = re.compile(
    r"(?:[$A-Z_a-z][$\w]*)(?:\.(?:[$A-Z_a-z][$\w]*))*", re.ASCII
)


def unwrap_jsonp(payload: str, expected_callback: str | None = None) -> Any:
    """Decode a JSONP payload without executing its JavaScript wrapper."""
    if not isinstance(payload, str):
        raise TypeError("JSONP payload must be a string")

    text = payload.strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()

    opening = text.find("(")
    if opening <= 0 or not text.endswith(")"):
        raise ValueError("Invalid JSONP wrapper")

    callback = text[:opening].strip()
    if _CALLBACK_RE.fullmatch(callback) is None:
        raise ValueError("Invalid JSONP callback name")
    if any(part.startswith("__") for part in callback.split(".")):
        raise ValueError("Unsafe JSONP callback name")
    if expected_callback is not None and callback != expected_callback:
        raise ValueError(
            f"Unexpected JSONP callback: expected {expected_callback!r}, got {callback!r}"
        )

    try:
        return json.loads(text[opening + 1 : -1])
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON inside JSONP response") from exc
