"""OpenTelemetry trace parser for importing HTTP spans as capture sessions."""

from __future__ import annotations

import contextlib
import fnmatch
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from toolwright.core.capture.path_blocklist import is_blocked_path
from toolwright.models.capture import (
    CaptureSession,
    CaptureSource,
    HttpExchange,
    HTTPMethod,
)

SpanRecord = tuple[dict[str, Any], dict[str, Any]]


class OTELParser:
    """Parse OpenTelemetry trace exports into CaptureSession objects."""

    STATIC_EXTENSIONS = (
        ".css",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".map",
        ".js",
        ".ts",
    )

    def __init__(self, allowed_hosts: list[str] | None = None) -> None:
        self.allowed_hosts = allowed_hosts or []
        self.warnings: list[str] = []
        self.stats: dict[str, int] = {}
        self._reset_stats()

    def parse_file(self, path: Path, name: str | None = None) -> CaptureSession:
        """Parse an OTEL export file (JSON or NDJSON) into a CaptureSession."""
        self.warnings = []
        self._reset_stats()

        payload = self._load_payload(path)
        if payload is None:
            return CaptureSession(
                name=name or path.stem,
                source=CaptureSource.OTEL,
                source_file=str(path),
                allowed_hosts=self.allowed_hosts,
                warnings=self.warnings,
            )

        span_records = self._extract_spans(payload)
        self.stats["total_spans"] = len(span_records)

        exchanges: list[HttpExchange] = []
        seen_span_keys: set[tuple[str, str]] = set()

        for span, resource_attrs in span_records:
            trace_id = str(span.get("traceId", ""))
            span_id = str(span.get("spanId", ""))
            span_key = (trace_id, span_id)

            if trace_id and span_id and span_key in seen_span_keys:
                self.stats["filtered_duplicate"] += 1
                continue

            exchange = self._parse_span(span, resource_attrs)
            if exchange is None:
                continue

            if trace_id and span_id:
                seen_span_keys.add(span_key)
            exchanges.append(exchange)
            self.stats["imported"] += 1

        filtered_total = (
            self.stats["filtered_non_http"]
            + self.stats["filtered_missing_url"]
            + self.stats["filtered_host"]
            + self.stats["filtered_static"]
            + self.stats["filtered_duplicate"]
        )

        return CaptureSession(
            name=name or path.stem,
            source=CaptureSource.OTEL,
            source_file=str(path),
            allowed_hosts=self.allowed_hosts,
            exchanges=exchanges,
            total_requests=self.stats["total_spans"],
            filtered_requests=filtered_total,
            warnings=self.warnings,
        )

    def _reset_stats(self) -> None:
        self.stats = {
            "total_spans": 0,
            "imported": 0,
            "filtered_non_http": 0,
            "filtered_missing_url": 0,
            "filtered_host": 0,
            "filtered_static": 0,
            "filtered_duplicate": 0,
        }

    def _load_payload(self, path: Path) -> dict[str, Any] | list[Any] | None:
        if not path.exists():
            self.warnings.append(f"OTEL file not found: {path}")
            return None

        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.warnings.append(f"Error reading OTEL file: {exc}")
            return None

        try:
            loaded = json.loads(raw_text)
            if isinstance(loaded, dict | list):
                return loaded
            self.warnings.append("Unsupported OTEL payload structure (expected JSON object/list)")
            return None
        except json.JSONDecodeError:
            pass

        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(raw_text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                self.warnings.append(f"Invalid NDJSON line {line_no}: {exc}")
                continue
            if isinstance(record, dict):
                records.append(record)

        if records:
            return records

        self.warnings.append("Invalid OTEL payload: expected JSON or NDJSON")
        return None

    def _extract_spans(
        self,
        payload: dict[str, Any] | list[Any],
        inherited_resource_attrs: dict[str, Any] | None = None,
    ) -> list[SpanRecord]:
        resource_attrs = inherited_resource_attrs or {}
        records: list[SpanRecord] = []

        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict | list):
                    records.extend(self._extract_spans(item, resource_attrs))
            return records

        if "resourceSpans" in payload:
            resource_spans = payload.get("resourceSpans")
            if isinstance(resource_spans, list):
                for resource_span in resource_spans:
                    if not isinstance(resource_span, dict):
                        continue
                    attrs = self._attributes_to_dict(
                        resource_span.get("resource", {}).get("attributes", [])
                    )
                    merged_attrs = {**resource_attrs, **attrs}
                    scope_spans = resource_span.get("scopeSpans")
                    if not isinstance(scope_spans, list):
                        scope_spans = resource_span.get("instrumentationLibrarySpans", [])
                    if not isinstance(scope_spans, list):
                        scope_spans = []
                    for scope_span in scope_spans:
                        if not isinstance(scope_span, dict):
                            continue
                        spans = scope_span.get("spans", [])
                        if not isinstance(spans, list):
                            continue
                        for span in spans:
                            if isinstance(span, dict):
                                records.append((span, merged_attrs))
            return records

        if "span" in payload and isinstance(payload["span"], dict):
            attrs = self._attributes_to_dict(payload.get("resource", {}).get("attributes", []))
            merged_attrs = {**resource_attrs, **attrs}
            records.append((payload["span"], merged_attrs))
            return records

        if "spans" in payload and isinstance(payload["spans"], list):
            for span in payload["spans"]:
                if isinstance(span, dict):
                    records.append((span, resource_attrs))
            return records

        if "traceId" in payload and "spanId" in payload:
            records.append((payload, resource_attrs))

        return records

    def _parse_span(
        self,
        span: dict[str, Any],
        resource_attrs: dict[str, Any],
    ) -> HttpExchange | None:
        attrs = self._attributes_to_dict(span.get("attributes", []))

        method_raw = self._first_string(attrs, ("http.request.method", "http.method"))
        if not method_raw:
            self.stats["filtered_non_http"] += 1
            return None

        method_text = method_raw.upper()
        try:
            method = HTTPMethod(method_text)
        except ValueError:
            self.stats["filtered_non_http"] += 1
            return None

        url = self._extract_url(attrs)
        if not url:
            self.stats["filtered_missing_url"] += 1
            return None

        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"
        if not host:
            self.stats["filtered_missing_url"] += 1
            return None

        if not self._is_allowed_host(host):
            self.stats["filtered_host"] += 1
            return None

        if any(path.lower().endswith(ext) for ext in self.STATIC_EXTENSIONS):
            self.stats["filtered_static"] += 1
            return None

        if is_blocked_path(path):
            self.stats["filtered_static"] += 1
            return None

        request_headers = self._extract_headers(attrs, "http.request.header.")
        response_headers = self._extract_headers(attrs, "http.response.header.")
        request_body = self._first_string(
            attrs,
            ("http.request.body", "http.request.body.content"),
        )
        response_body = self._first_string(
            attrs,
            ("http.response.body", "http.response.body.content"),
        )

        status = self._first_int(attrs, ("http.response.status_code", "http.status_code"))
        start_time = self._parse_unix_nano(span.get("startTimeUnixNano"))
        end_time = self._parse_unix_nano(span.get("endTimeUnixNano"))
        duration_ms: float | None = None
        if start_time and end_time:
            duration_ms = max((end_time - start_time).total_seconds() * 1000.0, 0.0)

        notes: dict[str, Any] = {
            "trace_id": span.get("traceId"),
            "span_id": span.get("spanId"),
            "parent_span_id": span.get("parentSpanId"),
            "span_name": span.get("name"),
            "span_kind": span.get("kind"),
        }
        if "service.name" in resource_attrs:
            notes["service_name"] = resource_attrs["service.name"]

        return HttpExchange(
            url=url,
            method=method,
            host=host,
            path=path,
            request_headers=request_headers,
            request_body=request_body,
            request_body_json=self._try_parse_json(request_body),
            response_status=status,
            response_headers=response_headers,
            response_body=response_body,
            response_body_json=self._try_parse_json(response_body),
            response_content_type=self._first_string(
                attrs,
                ("http.response.header.content-type", "http.response_content_type"),
            ),
            timestamp=start_time,
            duration_ms=duration_ms,
            source=CaptureSource.OTEL,
            notes=notes,
        )

    def _extract_url(self, attrs: dict[str, Any]) -> str | None:
        full_url = self._first_string(attrs, ("url.full", "http.url"))
        if full_url:
            return full_url

        scheme = self._first_string(attrs, ("url.scheme", "http.scheme")) or "https"
        host = self._first_string(
            attrs,
            ("server.address", "http.host", "net.peer.name"),
        )
        if not host:
            return None

        port = self._first_int(attrs, ("server.port", "net.peer.port"))
        path = self._first_string(attrs, ("url.path", "http.target", "http.route")) or "/"
        query = self._first_string(attrs, ("url.query",))
        if not path.startswith("/"):
            path = f"/{path}"

        netloc = host if port is None else f"{host}:{port}"
        query_part = f"?{query}" if query else ""
        return f"{scheme}://{netloc}{path}{query_part}"

    def _extract_headers(self, attrs: dict[str, Any], prefix: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in attrs.items():
            if not key.startswith(prefix):
                continue
            header_name = key.removeprefix(prefix)
            if not header_name:
                continue
            headers[header_name] = self._stringify_value(value)
        return headers

    def _attributes_to_dict(self, attributes: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if not isinstance(attributes, list):
            return result

        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            key = attribute.get("key")
            if not isinstance(key, str) or not key:
                continue
            value = self._decode_otel_value(attribute.get("value"))
            result[key] = value
        return result

    def _decode_otel_value(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        if "stringValue" in value:
            return value["stringValue"]
        if "boolValue" in value:
            return bool(value["boolValue"])
        if "intValue" in value:
            with contextlib.suppress(ValueError, TypeError):
                return int(value["intValue"])
            return value["intValue"]
        if "doubleValue" in value:
            with contextlib.suppress(ValueError, TypeError):
                return float(value["doubleValue"])
            return value["doubleValue"]
        if "bytesValue" in value:
            return value["bytesValue"]
        if "arrayValue" in value:
            raw_values = value["arrayValue"].get("values", [])
            if isinstance(raw_values, list):
                return [self._decode_otel_value(item) for item in raw_values]
        if "kvlistValue" in value:
            kv_pairs = value["kvlistValue"].get("values", [])
            if isinstance(kv_pairs, list):
                parsed: dict[str, Any] = {}
                for item in kv_pairs:
                    if not isinstance(item, dict):
                        continue
                    item_key = item.get("key")
                    if not isinstance(item_key, str):
                        continue
                    parsed[item_key] = self._decode_otel_value(item.get("value"))
                return parsed
        return value

    def _first_string(self, attrs: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = attrs.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
                continue
            if isinstance(value, int | float):
                return str(value)
        return None

    def _first_int(self, attrs: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = attrs.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                with contextlib.suppress(ValueError):
                    return int(value)
        return None

    def _parse_unix_nano(self, value: Any) -> datetime | None:
        if value is None:
            return None

        with contextlib.suppress(ValueError, TypeError, OSError):
            nanos = int(value)
            seconds, remainder = divmod(nanos, 1_000_000_000)
            return datetime.fromtimestamp(seconds, tz=UTC).replace(
                microsecond=remainder // 1000
            )
        return None

    def _stringify_value(self, value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(self._stringify_value(item) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, separators=(",", ":"))
        return str(value)

    def _is_allowed_host(self, host: str) -> bool:
        if not self.allowed_hosts:
            return True

        for pattern in self.allowed_hosts:
            if pattern.startswith("*."):
                suffix = pattern[1:]
                if host == pattern[2:] or host.endswith(suffix):
                    return True
            elif fnmatch.fnmatch(host, pattern) or host == pattern:
                return True

        return False

    def _try_parse_json(self, text: str | None) -> dict[str, Any] | list[Any] | None:
        if not text:
            return None
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            parsed = json.loads(text)
            if isinstance(parsed, dict | list):
                return parsed
        return None
