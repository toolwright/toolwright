"""Capture-related data models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class HTTPMethod(StrEnum):
    """HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


class CaptureSource(StrEnum):
    """Source of captured traffic."""

    HAR = "har"
    OTEL = "otel"
    PLAYWRIGHT = "playwright"
    PROXY = "proxy"
    MANUAL = "manual"
    WEBMCP = "webmcp"


class HttpExchange(BaseModel):
    """A single HTTP request/response pair."""

    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Request
    url: str
    method: HTTPMethod
    host: str = ""
    path: str = ""
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: str | None = None
    request_body_json: dict[str, Any] | list[Any] | None = None

    # Response
    response_status: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: str | None = None
    response_body_json: dict[str, Any] | list[Any] | None = None
    response_content_type: str | None = None

    # Metadata
    timestamp: datetime | None = None
    duration_ms: float | None = None
    source: CaptureSource = CaptureSource.MANUAL

    # Redaction tracking
    redacted_fields: list[str] = Field(default_factory=list)

    # Additional context
    notes: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Extract host and path from URL if not set."""
        if self.url and not self.host:
            from urllib.parse import urlparse

            parsed = urlparse(self.url)
            object.__setattr__(self, "host", parsed.netloc)
            object.__setattr__(self, "path", parsed.path or "/")


class CaptureSession(BaseModel):
    """A collection of captured HTTP exchanges."""

    # Identity
    id: str = Field(default_factory=lambda: _generate_capture_id())

    # Metadata
    name: str | None = None
    description: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: CaptureSource = CaptureSource.HAR
    source_file: str | None = None

    # Allowed hosts (required for capture)
    allowed_hosts: list[str] = Field(default_factory=list)

    # Exchanges
    exchanges: list[HttpExchange] = Field(default_factory=list)

    # Statistics
    total_requests: int = 0
    filtered_requests: int = 0
    redacted_count: int = 0

    # Warnings/errors during import
    warnings: list[str] = Field(default_factory=list)


def _generate_capture_id() -> str:
    """Generate a capture ID in format cap_YYYYMMDD_random8."""
    date_part = datetime.now(UTC).strftime("%Y%m%d")
    random_part = uuid.uuid4().hex[:8]
    return f"cap_{date_part}_{random_part}"
