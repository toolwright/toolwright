"""Tests for response size limit enforcement.

Tests that the MCP server blocks responses exceeding the configured
maximum size via the TOOLWRIGHT_MAX_RESPONSE_BYTES setting.
"""

from __future__ import annotations

import os

import pytest

from toolwright.models.decision import ReasonCode


# ---------------------------------------------------------------------------
# Tests: ReasonCode for oversized responses
# ---------------------------------------------------------------------------


class TestReasonCode:
    """Verify DENIED_RESPONSE_TOO_LARGE exists."""

    def test_response_too_large_reason_code_exists(self):
        assert hasattr(ReasonCode, "DENIED_RESPONSE_TOO_LARGE")
        assert ReasonCode.DENIED_RESPONSE_TOO_LARGE == "denied_response_too_large"


# ---------------------------------------------------------------------------
# Tests: _check_response_size helper
# ---------------------------------------------------------------------------


class TestCheckResponseSize:
    """Test the response size check logic."""

    def test_small_response_is_allowed(self):
        """Responses under the limit should pass."""
        from toolwright.mcp.server import _check_response_size

        # 1KB response, 10MB limit
        _check_response_size(content_length=1024, max_bytes=10 * 1024 * 1024)

    def test_exact_limit_is_allowed(self):
        """Response exactly at the limit should pass."""
        from toolwright.mcp.server import _check_response_size

        _check_response_size(content_length=1000, max_bytes=1000)

    def test_over_limit_raises(self):
        """Response over the limit should raise RuntimeBlockError."""
        from toolwright.core.network_safety import RuntimeBlockError
        from toolwright.mcp.server import _check_response_size

        with pytest.raises(RuntimeBlockError) as exc_info:
            _check_response_size(content_length=2000, max_bytes=1000)
        assert exc_info.value.reason_code == ReasonCode.DENIED_RESPONSE_TOO_LARGE

    def test_no_content_length_passes(self):
        """When content-length is None (not provided), skip the check."""
        from toolwright.mcp.server import _check_response_size

        _check_response_size(content_length=None, max_bytes=1000)

    def test_zero_max_bytes_disables_check(self):
        """When max_bytes is 0, the check is disabled (unlimited)."""
        from toolwright.mcp.server import _check_response_size

        _check_response_size(content_length=999_999_999, max_bytes=0)


# ---------------------------------------------------------------------------
# Tests: Default and env-based configuration
# ---------------------------------------------------------------------------


class TestMaxResponseBytesConfig:
    """Test that max response bytes can be configured via env."""

    def test_default_max_response_bytes(self):
        """Default should be 10MB."""
        from toolwright.mcp.server import DEFAULT_MAX_RESPONSE_BYTES

        assert DEFAULT_MAX_RESPONSE_BYTES == 10 * 1024 * 1024

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        """TOOLWRIGHT_MAX_RESPONSE_BYTES env var should override default."""
        from toolwright.mcp.server import get_max_response_bytes

        monkeypatch.setenv("TOOLWRIGHT_MAX_RESPONSE_BYTES", "5000")
        assert get_max_response_bytes() == 5000

    def test_env_zero_means_unlimited(self, monkeypatch: pytest.MonkeyPatch):
        """Setting 0 means unlimited."""
        from toolwright.mcp.server import get_max_response_bytes

        monkeypatch.setenv("TOOLWRIGHT_MAX_RESPONSE_BYTES", "0")
        assert get_max_response_bytes() == 0

    def test_env_unset_uses_default(self, monkeypatch: pytest.MonkeyPatch):
        """When env var is not set, use default."""
        from toolwright.mcp.server import get_max_response_bytes

        monkeypatch.delenv("TOOLWRIGHT_MAX_RESPONSE_BYTES", raising=False)
        assert get_max_response_bytes() == 10 * 1024 * 1024
