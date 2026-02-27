"""Tests for HARParser handling of JSON arrays in request/response bodies."""

from __future__ import annotations

import json
from typing import Any

from toolwright.core.capture.har_parser import HARParser


def _make_har_with_body(
    *,
    response_body: str,
    request_body: str | None = None,
    method: str = "GET",
    url: str = "https://api.example.com/items",
    content_type: str = "application/json",
) -> dict[str, Any]:
    """Build a minimal HAR dict with a single entry."""
    entry: dict[str, Any] = {
        "startedDateTime": "2024-01-01T00:00:00Z",
        "time": 100,
        "request": {
            "method": method,
            "url": url,
            "headers": [],
        },
        "response": {
            "status": 200,
            "headers": [{"name": "content-type", "value": content_type}],
            "content": {"text": response_body, "mimeType": content_type},
        },
    }
    if request_body is not None:
        entry["request"]["postData"] = {"text": request_body}
    return {"log": {"entries": [entry]}}


class TestTryParseJsonArrays:
    """Test that _try_parse_json preserves JSON arrays."""

    def test_response_body_json_array_preserved(self) -> None:
        """JSON arrays in response bodies should be parsed, not dropped."""
        body = json.dumps([{"id": 1, "name": "foo"}, {"id": 2, "name": "bar"}])
        har = _make_har_with_body(response_body=body)
        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_dict(har)

        assert len(session.exchanges) == 1
        exchange = session.exchanges[0]
        assert exchange.response_body_json is not None
        assert isinstance(exchange.response_body_json, list)
        assert len(exchange.response_body_json) == 2
        assert exchange.response_body_json[0]["id"] == 1

    def test_request_body_json_array_preserved(self) -> None:
        """JSON arrays in request bodies should be parsed, not dropped."""
        body = json.dumps([{"action": "create"}, {"action": "update"}])
        har = _make_har_with_body(
            response_body="{}",
            request_body=body,
            method="POST",
        )
        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_dict(har)

        assert len(session.exchanges) == 1
        exchange = session.exchanges[0]
        assert exchange.request_body_json is not None
        assert isinstance(exchange.request_body_json, list)
        assert len(exchange.request_body_json) == 2

    def test_dict_body_still_works(self) -> None:
        """Regular JSON objects should still be parsed correctly."""
        body = json.dumps({"id": 1, "name": "test"})
        har = _make_har_with_body(response_body=body)
        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_dict(har)

        assert len(session.exchanges) == 1
        exchange = session.exchanges[0]
        assert exchange.response_body_json is not None
        assert isinstance(exchange.response_body_json, dict)
        assert exchange.response_body_json["id"] == 1

    def test_non_json_body_returns_none(self) -> None:
        """Non-JSON text should return None for body_json."""
        parser = HARParser(allowed_hosts=["api.example.com"])
        result = parser._try_parse_json("<html>not json</html>")
        assert result is None

    def test_scalar_json_returns_none(self) -> None:
        """Scalar JSON values (strings, numbers) should return None."""
        parser = HARParser()
        assert parser._try_parse_json('"just a string"') is None
        assert parser._try_parse_json("42") is None
        assert parser._try_parse_json("true") is None
        assert parser._try_parse_json("null") is None

    def test_empty_array_preserved(self) -> None:
        """Empty JSON arrays should be preserved (not treated as falsy)."""
        parser = HARParser()
        result = parser._try_parse_json("[]")
        assert result is not None
        assert result == []
