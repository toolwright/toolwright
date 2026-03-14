"""Tests for URL validation and allowed-hosts cleaning in mint.

Phase 3.1 (V-004): Invalid URLs like 'notaurl' should be rejected
before reaching Playwright, preventing 60s hangs.

Phase 3.2 (V-005): Protocol prefixes on --allowed-hosts should be
stripped so that host matching works correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from toolwright.cli.mint import run_mint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mint_kwargs(**overrides: object) -> dict:
    """Return minimal run_mint kwargs with sensible defaults."""
    defaults: dict = {
        "start_url": "https://example.com",
        "allowed_hosts": ["example.com"],
        "name": None,
        "scope_name": "default",
        "headless": True,
        "script_path": None,
        "duration_seconds": 10,
        "output_root": "/tmp/tw-test",
        "deterministic": False,
        "print_mcp_config": False,
        "runtime_mode": "local",
        "runtime_build": False,
        "runtime_tag": None,
        "runtime_version_pin": None,
        "auth_profile": None,
        "webmcp": False,
        "redaction_profile": None,
        "verbose": False,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Phase 3.1: URL validation
# ---------------------------------------------------------------------------


class TestURLValidation:
    """Phase 3.1: reject invalid URLs before Playwright import."""

    def test_invalid_url_bare_word_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A bare word like 'notaurl' should exit(1) with an error message
        mentioning 'Invalid URL' -- not silently failing via ImportError."""
        with pytest.raises(SystemExit) as exc_info:
            run_mint(**_mint_kwargs(start_url="notaurl"))
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid URL" in captured.err

    def test_invalid_url_no_scheme_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """URL without scheme like 'example.com' should be rejected with
        a clear error message."""
        with pytest.raises(SystemExit) as exc_info:
            run_mint(**_mint_kwargs(start_url="example.com"))
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid URL" in captured.err

    def test_invalid_url_scheme_only_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """URL like 'http://' with no netloc should be rejected."""
        with pytest.raises(SystemExit) as exc_info:
            run_mint(**_mint_kwargs(start_url="http://"))
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid URL" in captured.err

    def test_valid_url_passes_validation(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A valid URL like 'https://example.com' should pass URL validation.

        We mock the PlaywrightCapture import to avoid needing a browser.
        The function will proceed past URL validation; we verify no
        'Invalid URL' message appeared on stderr.
        """
        mock_capture = MagicMock()
        mock_capture.side_effect = RuntimeError("stop-after-validation")
        with (
            patch.dict(
                "sys.modules",
                {"toolwright.core.capture.playwright_capture": MagicMock(PlaywrightCapture=mock_capture)},
            ),
            pytest.raises((SystemExit, RuntimeError)),
        ):
            run_mint(**_mint_kwargs(start_url="https://example.com"))
        captured = capsys.readouterr()
        assert "Invalid URL" not in captured.err


# ---------------------------------------------------------------------------
# Phase 3.2: allowed-hosts protocol stripping
# ---------------------------------------------------------------------------


class TestAllowedHostsCleaning:
    """Phase 3.2: strip protocol prefixes from --allowed-hosts."""

    def test_protocol_stripped_from_allowed_host(self) -> None:
        """'https://api.example.com' should become 'api.example.com'."""
        mock_cls = MagicMock()
        mock_cls.side_effect = RuntimeError("stop")
        mock_module = MagicMock(PlaywrightCapture=mock_cls)

        with patch.dict(
            "sys.modules",
            {"toolwright.core.capture.playwright_capture": mock_module},
        ), pytest.raises((SystemExit, RuntimeError)):
            run_mint(
                **_mint_kwargs(
                    start_url="https://app.example.com",
                    allowed_hosts=["https://api.example.com"],
                )
            )
        # PlaywrightCapture should have been called with cleaned hosts
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args
        hosts = call_kwargs.kwargs.get("allowed_hosts") or call_kwargs[1].get(
            "allowed_hosts"
        )
        assert hosts is not None
        assert "api.example.com" in hosts
        assert "https://api.example.com" not in hosts

    def test_plain_host_unchanged(self) -> None:
        """'api.example.com' (no protocol) should be passed through as-is."""
        mock_cls = MagicMock()
        mock_cls.side_effect = RuntimeError("stop")
        mock_module = MagicMock(PlaywrightCapture=mock_cls)

        with patch.dict(
            "sys.modules",
            {"toolwright.core.capture.playwright_capture": mock_module},
        ), pytest.raises((SystemExit, RuntimeError)):
            run_mint(
                **_mint_kwargs(
                    start_url="https://app.example.com",
                    allowed_hosts=["api.example.com"],
                )
            )
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args
        hosts = call_kwargs.kwargs.get("allowed_hosts") or call_kwargs[1].get(
            "allowed_hosts"
        )
        assert hosts is not None
        assert "api.example.com" in hosts
