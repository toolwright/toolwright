"""Tests for MCP result → pipeline envelope normalizer."""

import json


class TestNormalizeMcpResult:
    """Test normalize_mcp_result converts CallToolResult to pipeline envelope."""

    def test_success_text_content(self):
        from toolwright.overlay.normalizer import normalize_mcp_result

        # Simulate a CallToolResult-like object with text content
        result = _make_result(
            content=[_text_content('{"repos": ["a", "b"]}')],
            is_error=False,
        )
        envelope = normalize_mcp_result("list_repos", result)

        assert envelope["status_code"] == 200
        assert envelope["action"] == "list_repos"
        # JSON text should be parsed into data
        assert envelope["data"] == {"repos": ["a", "b"]}

    def test_success_plain_text(self):
        from toolwright.overlay.normalizer import normalize_mcp_result

        result = _make_result(
            content=[_text_content("Hello world")],
            is_error=False,
        )
        envelope = normalize_mcp_result("greet", result)

        assert envelope["status_code"] == 200
        assert envelope["data"] == "Hello world"

    def test_error_result(self):
        from toolwright.overlay.normalizer import normalize_mcp_result

        result = _make_result(
            content=[_text_content("Not found: repo xyz")],
            is_error=True,
        )
        envelope = normalize_mcp_result("get_repo", result)

        assert envelope["status_code"] == 500
        assert envelope["action"] == "get_repo"
        assert "Not found" in envelope["data"]

    def test_multiple_text_blocks_concatenated(self):
        from toolwright.overlay.normalizer import normalize_mcp_result

        result = _make_result(
            content=[
                _text_content("Part 1"),
                _text_content("Part 2"),
                _text_content("Part 3"),
            ],
            is_error=False,
        )
        envelope = normalize_mcp_result("multi", result)

        assert envelope["status_code"] == 200
        # Multiple text blocks should be concatenated with newlines
        assert "Part 1" in envelope["data"]
        assert "Part 2" in envelope["data"]
        assert "Part 3" in envelope["data"]

    def test_empty_content(self):
        from toolwright.overlay.normalizer import normalize_mcp_result

        result = _make_result(content=[], is_error=False)
        envelope = normalize_mcp_result("empty", result)

        assert envelope["status_code"] == 200
        assert envelope["action"] == "empty"
        assert envelope["data"] == ""

    def test_non_text_content_graceful_degradation(self):
        """Non-text content (e.g. image) should not crash, produce a placeholder."""
        from toolwright.overlay.normalizer import normalize_mcp_result

        result = _make_result(
            content=[_image_content("base64data", "image/png")],
            is_error=False,
        )
        envelope = normalize_mcp_result("screenshot", result)

        assert envelope["status_code"] == 200
        # Should not crash; data should indicate non-text content
        assert isinstance(envelope["data"], str)

    def test_mixed_text_and_non_text(self):
        """Mixed content: extract text, skip non-text."""
        from toolwright.overlay.normalizer import normalize_mcp_result

        result = _make_result(
            content=[
                _text_content("Here is the result"),
                _image_content("base64", "image/png"),
                _text_content("End of result"),
            ],
            is_error=False,
        )
        envelope = normalize_mcp_result("mixed", result)

        assert envelope["status_code"] == 200
        assert "Here is the result" in envelope["data"]
        assert "End of result" in envelope["data"]

    def test_json_in_single_text_block_parsed(self):
        """When a single text block contains valid JSON, parse it into data."""
        from toolwright.overlay.normalizer import normalize_mcp_result

        payload = {"items": [1, 2, 3], "total": 3}
        result = _make_result(
            content=[_text_content(json.dumps(payload))],
            is_error=False,
        )
        envelope = normalize_mcp_result("query", result)

        assert envelope["data"] == payload

    def test_json_array_in_single_text_block_parsed(self):
        from toolwright.overlay.normalizer import normalize_mcp_result

        payload = [{"id": 1}, {"id": 2}]
        result = _make_result(
            content=[_text_content(json.dumps(payload))],
            is_error=False,
        )
        envelope = normalize_mcp_result("list", result)

        assert envelope["data"] == payload


# -- Helpers for building mock MCP result objects ---


class _MockContent:
    def __init__(self, type: str, **kwargs):
        self.type = type
        for k, v in kwargs.items():
            setattr(self, k, v)


class _MockCallToolResult:
    def __init__(self, content, is_error):
        self.content = content
        self.isError = is_error


def _make_result(content, is_error):
    return _MockCallToolResult(content=content, is_error=is_error)


def _text_content(text):
    return _MockContent(type="text", text=text)


def _image_content(data, mime_type):
    return _MockContent(type="image", data=data, mimeType=mime_type)
