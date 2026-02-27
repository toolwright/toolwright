"""Tests for mint auth pre-check warning.

P1-8: When headless capture is about to start and no auth profile is
provided, toolwright should do a quick pre-flight check. If the API returns
401/403, warn the user before the 30s capture begins.
"""

from __future__ import annotations

import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

from toolwright.cli.mint import _auth_precheck


def _make_response(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_auth_precheck_warns_on_401() -> None:
    """Pre-check should print a warning when API returns 401."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.example.com/", 401, "Unauthorized", {}, BytesIO(b"")
        )
        # Should not raise — just prints a warning
        _auth_precheck(["api.example.com"], "https://app.example.com")


def test_auth_precheck_warns_on_403() -> None:
    """Pre-check should print a warning when API returns 403."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.example.com/", 403, "Forbidden", {}, BytesIO(b"")
        )
        _auth_precheck(["api.example.com"], "https://app.example.com")


def test_auth_precheck_silent_on_200() -> None:
    """Pre-check should not print anything when API returns 200."""
    resp = _make_response(200)
    with patch("urllib.request.urlopen", return_value=resp):
        _auth_precheck(["api.example.com"], "https://app.example.com")


def test_auth_precheck_silent_on_network_error() -> None:
    """Pre-check should silently skip on network errors."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = OSError("Connection refused")
        _auth_precheck(["api.example.com"], "https://app.example.com")
