"""Tests for OpenTelemetry capture parser."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.core.capture.otel_parser import OTELParser
from toolwright.models.capture import CaptureSource, HTTPMethod


def _write_otel_export(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "trace-export.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_parse_otlp_json_extracts_http_spans(tmp_path: Path) -> None:
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "checkout-api"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "abc123",
                                "spanId": "span-http",
                                "kind": "SPAN_KIND_CLIENT",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000500000000",
                                "attributes": [
                                    {
                                        "key": "http.request.method",
                                        "value": {"stringValue": "GET"},
                                    },
                                    {
                                        "key": "url.full",
                                        "value": {
                                            "stringValue": "https://api.example.com/users/123"
                                        },
                                    },
                                    {
                                        "key": "http.response.status_code",
                                        "value": {"intValue": "200"},
                                    },
                                ],
                            },
                            {
                                "traceId": "abc123",
                                "spanId": "span-db",
                                "kind": "SPAN_KIND_CLIENT",
                                "attributes": [
                                    {"key": "db.system", "value": {"stringValue": "postgresql"}}
                                ],
                            },
                        ]
                    }
                ],
            }
        ]
    }
    path = _write_otel_export(tmp_path, payload)
    parser = OTELParser(allowed_hosts=["api.example.com"])

    session = parser.parse_file(path, name="otel-import")

    assert session.name == "otel-import"
    assert session.source == CaptureSource.OTEL
    assert len(session.exchanges) == 1
    assert session.total_requests == 2
    assert session.filtered_requests == 1

    exchange = session.exchanges[0]
    assert exchange.source == CaptureSource.OTEL
    assert exchange.method == HTTPMethod.GET
    assert exchange.url == "https://api.example.com/users/123"
    assert exchange.host == "api.example.com"
    assert exchange.path == "/users/123"
    assert exchange.response_status == 200
    assert exchange.duration_ms == 500.0
    assert exchange.notes["trace_id"] == "abc123"
    assert exchange.notes["span_id"] == "span-http"
    assert exchange.notes["service_name"] == "checkout-api"


def test_parse_otlp_json_supports_legacy_http_attributes(tmp_path: Path) -> None:
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "def456",
                                "spanId": "span-legacy",
                                "attributes": [
                                    {"key": "http.method", "value": {"stringValue": "POST"}},
                                    {
                                        "key": "http.url",
                                        "value": {
                                            "stringValue": "https://api.example.com/orders"
                                        },
                                    },
                                    {"key": "http.status_code", "value": {"intValue": "201"}},
                                    {
                                        "key": "http.request.body",
                                        "value": {"stringValue": '{"amount": 10}'},
                                    },
                                    {
                                        "key": "http.response.body",
                                        "value": {"stringValue": '{"ok": true}'},
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    path = _write_otel_export(tmp_path, payload)
    parser = OTELParser(allowed_hosts=["api.example.com"])

    session = parser.parse_file(path)

    assert len(session.exchanges) == 1
    exchange = session.exchanges[0]
    assert exchange.method == HTTPMethod.POST
    assert exchange.response_status == 201
    assert exchange.request_body == '{"amount": 10}'
    assert exchange.response_body == '{"ok": true}'


def test_parse_otlp_json_filters_static_assets(tmp_path: Path) -> None:
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "ghi789",
                                "spanId": "span-api",
                                "attributes": [
                                    {
                                        "key": "http.request.method",
                                        "value": {"stringValue": "GET"},
                                    },
                                    {
                                        "key": "url.full",
                                        "value": {
                                            "stringValue": "https://api.example.com/users"
                                        },
                                    },
                                ],
                            },
                            {
                                "traceId": "ghi789",
                                "spanId": "span-static",
                                "attributes": [
                                    {
                                        "key": "http.request.method",
                                        "value": {"stringValue": "GET"},
                                    },
                                    {
                                        "key": "url.full",
                                        "value": {
                                            "stringValue": "https://api.example.com/static/app.js"
                                        },
                                    },
                                ],
                            },
                        ]
                    }
                ]
            }
        ]
    }
    path = _write_otel_export(tmp_path, payload)
    parser = OTELParser(allowed_hosts=["api.example.com"])

    session = parser.parse_file(path)

    assert len(session.exchanges) == 1
    assert session.exchanges[0].path == "/users"
    assert session.filtered_requests == 1
