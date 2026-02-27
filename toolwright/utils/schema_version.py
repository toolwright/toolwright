"""Artifact schema version utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

CURRENT_SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = {CURRENT_SCHEMA_VERSION}
DETERMINISTIC_TIMESTAMP = datetime(1970, 1, 1, tzinfo=UTC)


def resolve_schema_version(
    data: dict[str, Any],
    *,
    artifact: str,
    allow_legacy: bool = True,
) -> str:
    """Resolve and validate artifact schema version.

    Args:
        data: Loaded artifact payload.
        artifact: Artifact name for error messages.
        allow_legacy: If True, missing schema_version is treated as current.

    Returns:
        Supported schema version.

    Raises:
        ValueError: If schema version is unsupported or missing when required.
    """
    schema_version = data.get("schema_version")
    if schema_version is None:
        if allow_legacy:
            return CURRENT_SCHEMA_VERSION
        raise ValueError(f"{artifact} missing required 'schema_version'")

    if str(schema_version) not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise ValueError(
            f"Unsupported {artifact} schema_version '{schema_version}'. "
            f"Supported: {supported}"
        )

    return str(schema_version)


def resolve_generated_at(
    *,
    deterministic: bool,
    candidate: datetime | None = None,
) -> datetime:
    """Resolve generated_at timestamp for deterministic/non-deterministic builds."""
    if deterministic:
        return candidate or DETERMINISTIC_TIMESTAMP
    return datetime.now(UTC)
