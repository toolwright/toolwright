"""Sensitive field redaction for heal example values.

Redacts values at paths whose leaf key matches known sensitive patterns.
"""

from __future__ import annotations

SENSITIVE_PATTERNS = frozenset({
    "password",
    "secret",
    "token",
    "key",
    "auth",
    "ssn",
    "credit_card",
    "cvv",
})


def redact_examples(examples: dict[str, str]) -> dict[str, str]:
    """Redact sensitive values based on leaf key of dotted path."""
    result: dict[str, str] = {}
    for path, value in examples.items():
        leaf = path.rsplit(".", 1)[-1].rstrip("[]").lower()
        if any(pattern in leaf for pattern in SENSITIVE_PATTERNS):
            result[path] = "[REDACTED]"
        else:
            result[path] = value
    return result
