"""Tests for SSE/WebSocket detection and warning.

WebSocket and SSE entries should be detected, skipped, and produce clear
warnings rather than silently creating incomplete/empty tools.
"""

import json
import tempfile
from pathlib import Path

from toolwright.core.capture.har_parser import HARParser


def create_har_file(entries: list[dict]) -> Path:
    """Create a temporary HAR file with given entries."""
    har_data = {
        "log": {
            "version": "1.2",
            "entries": entries,
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".har", delete=False) as f:
        json.dump(har_data, f)
        return Path(f.name)


def make_entry(
    url: str,
    method: str = "GET",
    status: int = 200,
    content_type: str = "application/json",
    resource_type: str = "xhr",
    response_headers: list[dict] | None = None,
) -> dict:
    """Create a HAR entry with optional custom response headers."""
    headers = response_headers or [{"name": "content-type", "value": content_type}]
    return {
        "request": {
            "method": method,
            "url": url,
            "headers": [],
        },
        "response": {
            "status": status,
            "headers": headers,
            "content": {},
        },
        "_resourceType": resource_type,
    }


class TestWebSocketDetection:
    """WebSocket entries should be detected and skipped with a warning."""

    def test_websocket_resource_type_filtered(self):
        """Entries with _resourceType 'websocket' should not produce exchanges."""
        har_path = create_har_file([
            make_entry(
                "wss://api.example.com/ws/events",
                resource_type="websocket",
            ),
            make_entry("https://api.example.com/api/users", method="GET"),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 1
        assert session.exchanges[0].method.value == "GET"

    def test_websocket_produces_warning(self):
        """WebSocket entries should produce a warning message."""
        har_path = create_har_file([
            make_entry(
                "wss://api.example.com/ws/events",
                resource_type="websocket",
            ),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 0
        assert any("websocket" in w.lower() or "WebSocket" in w for w in session.warnings)

    def test_websocket_upgrade_header_detected(self):
        """WebSocket entries detected via upgrade header (when _resourceType is not websocket)."""
        har_path = create_har_file([
            make_entry(
                "https://api.example.com/ws/events",
                status=101,
                resource_type="xhr",
                response_headers=[
                    {"name": "content-type", "value": ""},
                    {"name": "upgrade", "value": "websocket"},
                ],
            ),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 0
        assert any("websocket" in w.lower() or "WebSocket" in w for w in session.warnings)


class TestSSEDetection:
    """SSE (text/event-stream) entries should be detected and skipped with a warning."""

    def test_sse_content_type_filtered(self):
        """Entries with text/event-stream content-type should not produce exchanges."""
        har_path = create_har_file([
            make_entry(
                "https://api.example.com/api/events",
                content_type="text/event-stream",
            ),
            make_entry("https://api.example.com/api/users", method="GET"),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 1
        assert session.exchanges[0].method.value == "GET"

    def test_sse_content_type_with_params_filtered(self):
        """SSE content-type with charset parameter should still be detected."""
        har_path = create_har_file([
            make_entry(
                "https://api.example.com/api/stream",
                content_type="text/event-stream; charset=utf-8",
            ),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 0
        assert any("SSE" in w or "event-stream" in w.lower() for w in session.warnings)

    def test_sse_produces_warning(self):
        """SSE entries should produce a warning message."""
        har_path = create_har_file([
            make_entry(
                "https://api.example.com/api/events",
                content_type="text/event-stream",
            ),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        assert len(session.exchanges) == 0
        assert any("SSE" in w or "event-stream" in w.lower() for w in session.warnings)


class TestMixedStreamingAndRegular:
    """Streaming entries should be filtered while regular API calls pass through."""

    def test_mixed_websocket_sse_and_regular(self):
        """All streaming entries filtered, all regular API calls kept."""
        har_path = create_har_file([
            make_entry("wss://api.example.com/ws", resource_type="websocket"),
            make_entry("https://api.example.com/api/stream", content_type="text/event-stream"),
            make_entry("https://api.example.com/api/users", method="GET"),
            make_entry("https://api.example.com/api/users", method="POST"),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        methods = sorted([ex.method.value for ex in session.exchanges])
        assert methods == ["GET", "POST"]
        assert len(session.warnings) >= 2  # At least one for WS, one for SSE
