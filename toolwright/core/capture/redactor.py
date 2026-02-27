"""Redaction of sensitive data from captures."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from toolwright.models.capture import CaptureSession, HttpExchange


class Redactor:
    """Redact sensitive data from captured traffic."""

    MAX_BODY_CHARS = 4096

    # Headers to always redact
    SENSITIVE_HEADERS = {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-access-token",
        "x-csrf-token",
        "x-xsrf-token",
        "proxy-authorization",
        "www-authenticate",
    }

    # Query param keys to redact
    SENSITIVE_PARAMS = {
        "token",
        "key",
        "api_key",
        "apikey",
        "api-key",
        "auth",
        "password",
        "secret",
        "signature",
        "session",
        "session_id",
        "sessionid",
        "access_token",
        "refresh_token",
    }

    # Patterns to redact from bodies
    SENSITIVE_PATTERNS = [
        # Bearer tokens
        (r"bearer\s+[a-zA-Z0-9\-_.]+", "[REDACTED_BEARER]"),
        # API keys in various formats
        (r"api[_-]?key[\"']?\s*[=:]\s*[\"']?[a-zA-Z0-9\-_]+", 'api_key="[REDACTED]"'),
        # Passwords
        (r"password[\"']?\s*[=:]\s*[\"']?[^\"'\s,}]+", 'password="[REDACTED]"'),
        # JWT tokens
        (r"eyJ[a-zA-Z0-9\-_]+\.eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+", "[REDACTED_JWT]"),
        # Basic auth
        (r"basic\s+[a-zA-Z0-9+/=]+", "[REDACTED_BASIC]"),
    ]

    # Compiled patterns
    _compiled_patterns: list[tuple[re.Pattern[str], str]] | None = None

    def __init__(
        self,
        extra_headers: set[str] | None = None,
        extra_params: set[str] | None = None,
        extra_patterns: list[tuple[str, str]] | None = None,
        profile: Any | None = None,
    ) -> None:
        """Initialize redactor with optional extra patterns or a RedactionProfile.

        Args:
            extra_headers: Additional headers to redact
            extra_params: Additional query params to redact
            extra_patterns: Additional regex patterns to redact
            profile: Optional RedactionProfile to apply (merges with defaults)
        """
        self.headers = self.SENSITIVE_HEADERS.copy()
        if extra_headers:
            self.headers.update(extra_headers)

        self.params = self.SENSITIVE_PARAMS.copy()
        if extra_params:
            self.params.update(extra_params)

        patterns = list(self.SENSITIVE_PATTERNS)
        if extra_patterns:
            patterns.extend(extra_patterns)

        # Apply RedactionProfile if provided
        if profile is not None:
            self.headers.update(h.lower() for h in profile.redact_headers)
            self.params.update(p.lower() for p in profile.redact_query_params)
            for body_pattern in profile.redact_body_patterns:
                # Body patterns from profiles use a generic replacement
                patterns.append((body_pattern, "[REDACTED_PII]"))
            if profile.max_body_chars != self.MAX_BODY_CHARS:
                self.MAX_BODY_CHARS = profile.max_body_chars

        self._compiled_patterns = [
            (re.compile(p, re.IGNORECASE), r) for p, r in patterns
        ]

    def redact_session(self, session: CaptureSession) -> CaptureSession:
        """Redact all sensitive data from a capture session.

        Args:
            session: CaptureSession to redact

        Returns:
            New CaptureSession with redacted data
        """
        redacted_exchanges = [
            self.redact_exchange(exchange) for exchange in session.exchanges
        ]

        redacted_count = sum(len(e.redacted_fields) for e in redacted_exchanges)

        return CaptureSession(
            id=session.id,
            name=session.name,
            description=session.description,
            created_at=session.created_at,
            source=session.source,
            source_file=session.source_file,
            allowed_hosts=session.allowed_hosts,
            exchanges=redacted_exchanges,
            total_requests=session.total_requests,
            filtered_requests=session.filtered_requests,
            redacted_count=redacted_count,
            warnings=session.warnings,
        )

    def redact_exchange(self, exchange: HttpExchange) -> HttpExchange:
        """Redact sensitive data from a single exchange.

        Args:
            exchange: HttpExchange to redact

        Returns:
            New HttpExchange with redacted data
        """
        redacted_fields: list[str] = []

        # Redact request headers
        redacted_request_headers, header_redactions = self._redact_headers(
            exchange.request_headers
        )
        redacted_fields.extend(f"request_header:{h}" for h in header_redactions)

        # Redact response headers
        redacted_response_headers, header_redactions = self._redact_headers(
            exchange.response_headers
        )
        redacted_fields.extend(f"response_header:{h}" for h in header_redactions)

        # Redact URL query params
        redacted_url = self._redact_url(exchange.url)
        if redacted_url != exchange.url:
            redacted_fields.append("url")

        # Redact request body
        redacted_request_body = exchange.request_body
        redacted_request_body_json = exchange.request_body_json
        request_schema_zeroed = False
        notes = dict(exchange.notes)
        if exchange.request_body:
            redacted_request_body = self._redact_text(exchange.request_body)
            if redacted_request_body != exchange.request_body:
                redacted_fields.append("request_body")
            redacted_request_body, was_truncated, digest = self._truncate_with_digest(
                redacted_request_body
            )
            notes["request_body_sha256"] = digest
            notes["request_body_truncated"] = was_truncated
            if was_truncated:
                redacted_fields.append("request_body_truncated")
                if exchange.request_body_json is not None:
                    redacted_request_body_json = self._schema_zero(exchange.request_body_json)
                    notes["schema_sample"] = True
                    request_schema_zeroed = True
                else:
                    redacted_request_body_json = None
        if not request_schema_zeroed and exchange.request_body_json and isinstance(exchange.request_body_json, dict):
            redacted_request_body_json = self._redact_dict(exchange.request_body_json)

        # Redact response body
        redacted_response_body = exchange.response_body
        redacted_response_body_json = exchange.response_body_json
        response_schema_zeroed = False
        if exchange.response_body:
            redacted_response_body = self._redact_text(exchange.response_body)
            if redacted_response_body != exchange.response_body:
                redacted_fields.append("response_body")
            redacted_response_body, was_truncated, digest = self._truncate_with_digest(
                redacted_response_body
            )
            notes["response_body_sha256"] = digest
            notes["response_body_truncated"] = was_truncated
            if was_truncated:
                redacted_fields.append("response_body_truncated")
                if exchange.response_body_json is not None:
                    redacted_response_body_json = self._schema_zero(exchange.response_body_json)
                    notes["schema_sample"] = True
                    response_schema_zeroed = True
                else:
                    redacted_response_body_json = None
        if not response_schema_zeroed and exchange.response_body_json and isinstance(exchange.response_body_json, dict):
            redacted_response_body_json = self._redact_dict(exchange.response_body_json)

        return HttpExchange(
            id=exchange.id,
            url=redacted_url,
            method=exchange.method,
            host=exchange.host,
            path=exchange.path,
            request_headers=redacted_request_headers,
            request_body=redacted_request_body,
            request_body_json=redacted_request_body_json,
            response_status=exchange.response_status,
            response_headers=redacted_response_headers,
            response_body=redacted_response_body,
            response_body_json=redacted_response_body_json,
            response_content_type=exchange.response_content_type,
            timestamp=exchange.timestamp,
            duration_ms=exchange.duration_ms,
            source=exchange.source,
            redacted_fields=redacted_fields,
            notes=notes,
        )

    def _redact_headers(
        self, headers: dict[str, str]
    ) -> tuple[dict[str, str], list[str]]:
        """Redact sensitive headers.

        Returns:
            Tuple of (redacted_headers, list of redacted header names)
        """
        redacted = {}
        redacted_names = []

        for name, value in headers.items():
            if name.lower() in self.headers:
                redacted[name] = "[REDACTED]"
                redacted_names.append(name)
            else:
                redacted[name] = value

        return redacted, redacted_names

    def _redact_url(self, url: str) -> str:
        """Redact sensitive query parameters from URL."""
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        parsed = urlparse(url)
        if not parsed.query:
            return url

        params = parse_qs(parsed.query, keep_blank_values=True)
        redacted = {}
        changed = False

        for key, values in params.items():
            if key.lower() in self.params:
                redacted[key] = ["[REDACTED]"]
                changed = True
            else:
                redacted[key] = values

        if not changed:
            return url

        # Flatten single-value lists
        flat_params = {
            k: v[0] if len(v) == 1 else v for k, v in redacted.items()
        }
        new_query = urlencode(flat_params, doseq=True)

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )

    def _redact_text(self, text: str) -> str:
        """Redact sensitive patterns from text."""
        if not self._compiled_patterns:
            return text

        result = text
        for pattern, replacement in self._compiled_patterns:
            result = pattern.sub(replacement, result)

        return result

    def _redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive keys from a dictionary."""
        redacted: dict[str, Any] = {}

        for key, value in data.items():
            if key.lower() in self.params:
                redacted[key] = "[REDACTED]"
            elif isinstance(value, dict):
                redacted[key] = self._redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = [
                    self._redact_dict(v) if isinstance(v, dict) else v for v in value
                ]
            elif isinstance(value, str):
                redacted[key] = self._redact_text(value)
            else:
                redacted[key] = value

        return redacted

    def _schema_zero(self, obj: Any, _depth: int = 0) -> Any:
        """Replace all leaf values with typed zero values for schema inference.

        Returns a structure with the same shape but zero-content values:
        str->"", int->0, float->0.0, bool->False, None->None.
        Lists are sampled at indices [0, len//2, len-1] and merged into
        a single-item list.
        """
        if _depth > 20:
            if isinstance(obj, dict):
                return {}
            if isinstance(obj, list):
                return []
            return obj

        if isinstance(obj, dict):
            return {k: self._schema_zero(v, _depth + 1) for k, v in obj.items()}

        if isinstance(obj, list):
            if not obj:
                return []
            # Deterministic sampling: [0, len//2, len-1]
            indices = sorted({0, len(obj) // 2, len(obj) - 1})
            indices = [i for i in indices if i < len(obj)]
            sampled = [obj[i] for i in indices]
            # Merge dict items into one dict, non-dict items are zeroed directly
            merged: dict[str, Any] = {}
            has_dicts = False
            for item in sampled:
                if isinstance(item, dict):
                    has_dicts = True
                    for k, v in item.items():
                        if k not in merged:
                            merged[k] = self._schema_zero(v, _depth + 1)
            if has_dicts:
                return [merged]
            # Non-dict list items: zero each sampled item
            return [self._schema_zero(sampled[0], _depth + 1)]

        if isinstance(obj, bool):
            return False
        if isinstance(obj, int):
            return 0
        if isinstance(obj, float):
            return 0.0
        if isinstance(obj, str):
            return ""
        return obj

    def _truncate_with_digest(self, value: str | None) -> tuple[str | None, bool, str | None]:
        """Return redacted excerpt with deterministic digest and truncation metadata."""
        if value is None:
            return None, False, None
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if len(value) <= self.MAX_BODY_CHARS:
            return value, False, digest
        excerpt = value[: self.MAX_BODY_CHARS] + "...[TRUNCATED]"
        return excerpt, True, digest
