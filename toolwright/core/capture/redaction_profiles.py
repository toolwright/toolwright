"""Redaction profiles — configurable redaction levels per docs/architecture.md §5.1.1."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedactionProfile:
    """A named redaction configuration."""

    id: str
    description: str
    redact_headers: list[str] = field(default_factory=list)
    redact_query_params: list[str] = field(default_factory=list)
    redact_body_patterns: list[str] = field(default_factory=list)
    truncate_bodies: bool = True
    max_body_chars: int = 4096


# --- Built-in profiles ---

DEFAULT_SAFE = RedactionProfile(
    id="default_safe",
    description="Standard redaction: auth headers, tokens, keys, cookies",
    redact_headers=[
        "authorization", "cookie", "set-cookie", "x-api-key",
        "x-auth-token", "x-access-token", "x-csrf-token",
        "x-xsrf-token", "x-forwarded-for", "proxy-authorization",
    ],
    redact_query_params=[
        "token", "key", "api_key", "apikey", "password", "secret",
        "signature", "session", "access_token", "refresh_token",
    ],
    redact_body_patterns=[
        r"(?i)bearer\s+[a-zA-Z0-9\-._~+/]+=*",
        r"(?i)api[_-]?key[\"']?\s*[:=]\s*[\"']?[\w\-]+",
        r"(?i)password[\"']?\s*[:=]\s*[\"'][^\"']+[\"']",
    ],
    truncate_bodies=True,
    max_body_chars=4096,
)

HIGH_RISK_PII = RedactionProfile(
    id="high_risk_pii",
    description="Aggressive PII detection: emails, phones, SSNs, addresses, names in addition to standard",
    redact_headers=[
        *DEFAULT_SAFE.redact_headers,
        "x-real-ip", "x-client-ip",
    ],
    redact_query_params=[
        *DEFAULT_SAFE.redact_query_params,
        "email", "phone", "ssn", "name", "address",
        "first_name", "last_name", "dob", "date_of_birth",
    ],
    redact_body_patterns=[
        *DEFAULT_SAFE.redact_body_patterns,
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # email
        r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # US phone
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
    ],
    truncate_bodies=True,
    max_body_chars=2048,  # More aggressive truncation
)

# Profile registry
PROFILES: dict[str, RedactionProfile] = {
    "default_safe": DEFAULT_SAFE,
    "high_risk_pii": HIGH_RISK_PII,
}


def get_profile(profile_id: str) -> RedactionProfile:
    """Get a redaction profile by ID. Raises ValueError if not found."""
    if profile_id not in PROFILES:
        raise ValueError(
            f"Unknown redaction profile '{profile_id}'. "
            f"Available: {', '.join(PROFILES.keys())}"
        )
    return PROFILES[profile_id]


def list_profiles() -> list[str]:
    """List available redaction profile IDs."""
    return list(PROFILES.keys())
