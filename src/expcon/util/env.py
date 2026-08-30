"""Environment variable redaction - never leak secrets."""

from __future__ import annotations

import re
from typing import Any

# Patterns that match common secret-bearing environment variable names
SECRET_PATTERNS = [
    re.compile(r"(?i)api[_-]?key"),
    re.compile(r"(?i)secret"),
    re.compile(r"(?i)token"),
    re.compile(r"(?i)password"),
    re.compile(r"(?i)credential"),
    re.compile(r"(?i)auth"),
    re.compile(r"(?i)oauth"),
    re.compile(r"(?i)kaggle.*dataset.*source"),
    re.compile(r"(?i)aws_"),
    re.compile(r"(?i)gcp_"),
    re.compile(r"(?i)private[_-]?key"),
]


def redact_secrets(data: Any) -> Any:
    """Recursively redact secret-bearing values, including Colab ConnectionInfo."""
    if isinstance(data, list):
        return [redact_secrets(item) for item in data]
    if not isinstance(data, dict):
        return data
    result: dict[str, Any] = {}
    for key, value in data.items():
        normalized = str(key).replace("_", "").replace("-", "").lower()
        if normalized in {"connectioninfo", "connection info"}:
            # ConnectionInfo is operationally transient; keeping host metadata
            # has no value to Expcon and risks retaining its bearer token.
            result[key] = "***REDACTED***"
            continue
        if isinstance(value, dict):
            result[key] = redact_secrets(value)
        elif isinstance(value, list):
            result[key] = [redact_secrets(item) for item in value]
        elif isinstance(value, str):
            if any(p.search(str(key)) for p in SECRET_PATTERNS):
                result[key] = "***REDACTED***"
            else:
                result[key] = value
        else:
            result[key] = value
    return result
