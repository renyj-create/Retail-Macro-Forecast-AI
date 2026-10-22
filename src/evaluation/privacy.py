"""Allowlisted summaries and conservative redaction for local evaluation traces."""

import json
import hashlib
import re
from typing import Any


MAX_TEXT = 3000
MAX_SUMMARY = 1200
MAX_ITEMS = 40

_SECRET_KEY = re.compile(r"(api.?key|secret|password|authorization|access.?token|refresh.?token|credential)", re.I)
_PRIVATE_KEY = re.compile(r"(image|base64|user.?id|customer.?id|phone|email|address)", re.I)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_KEY_VALUE_SECRET = re.compile(r"(?i)(api.?key|token|secret|password)\s*[:=]\s*[^\s,;]+")
_USER_ID = re.compile(r"(?i)(user[_ -]?id\s*[:=]?\s*|用户\s*)(\d{3,})")


def redact_text(value: str, limit: int = MAX_TEXT) -> str:
    value = _KEY_VALUE_SECRET.sub(r"\1=[REDACTED]", value)
    value = _EMAIL.sub("[REDACTED_EMAIL]", value)
    value = _PHONE.sub("[REDACTED_PHONE]", value)
    value = _USER_ID.sub(r"\1[REDACTED_ID]", value)
    if len(value) > limit:
        value = value[:limit] + "…[TRUNCATED]"
    return value


def sanitize(value: Any, *, text_limit: int = MAX_TEXT, depth: int = 0) -> Any:
    """Return JSON-safe data after recursive key-based redaction and truncation."""
    if depth > 8:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value, text_limit)
    if isinstance(value, dict):
        result = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                result["_truncated_items"] = True
                break
            safe_key = redact_text(str(key), 120)
            if "image" in safe_key.lower() or "base64" in safe_key.lower():
                result[safe_key] = "[OMITTED]"
            elif safe_key.lower() in ("query", "prompt", "user_content"):
                result[safe_key] = "[REDACTED_QUERY]"
            elif _SECRET_KEY.search(safe_key) or _PRIVATE_KEY.search(safe_key):
                result[safe_key] = "[REDACTED]"
            else:
                result[safe_key] = sanitize(item, text_limit=text_limit, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        return [sanitize(item, text_limit=text_limit, depth=depth + 1) for item in values[:MAX_ITEMS]] + (
            ["[TRUNCATED_ITEMS]"] if len(values) > MAX_ITEMS else []
        )
    try:
        return sanitize(value.model_dump(), text_limit=text_limit, depth=depth + 1)
    except Exception:
        return redact_text(str(value), text_limit)


def safe_summary(value: Any, limit: int = MAX_SUMMARY) -> str:
    """Create a bounded JSON/text summary without serializing whole workflow state."""
    safe = sanitize(value, text_limit=limit)
    try:
        rendered = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        rendered = str(safe)
    return redact_text(rendered, limit)


def report_excerpt(report: Any, limit: int = MAX_TEXT) -> str:
    if not isinstance(report, str):
        return ""
    return redact_text(report, limit)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
