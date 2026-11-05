from __future__ import annotations

import hashlib


MAX_STANDARD_NAME_LENGTH = 30
AUTOMATION_STANDARD_PREFIX = "AT-"


def automation_standard_name(name: str) -> str:
    """Return a deterministic, unique automation-only standard name."""
    value = str(name).strip()
    if value.startswith(AUTOMATION_STANDARD_PREFIX):
        return value[:MAX_STANDARD_NAME_LENGTH]
    candidate = f"{AUTOMATION_STANDARD_PREFIX}{value}"
    if len(candidate) <= MAX_STANDARD_NAME_LENGTH:
        return candidate
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:6]
    return f"{candidate[:MAX_STANDARD_NAME_LENGTH - 7]}-{digest}"
