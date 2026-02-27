"""Tests for CDN/analytics path blocklist."""

from __future__ import annotations

from toolwright.core.capture.path_blocklist import BLOCKED_PATH_PREFIXES, is_blocked_path


def test_cdn_cgi_rum_blocked() -> None:
    assert is_blocked_path("/cdn-cgi/rum") is True


def test_cdn_cgi_trace_blocked() -> None:
    assert is_blocked_path("/cdn-cgi/trace") is True


def test_beacon_blocked() -> None:
    assert is_blocked_path("/beacon") is True
    assert is_blocked_path("/beacon/track") is True


def test_collect_blocked() -> None:
    assert is_blocked_path("/collect") is True


def test_pixel_blocked() -> None:
    assert is_blocked_path("/pixel") is True


def test_analytics_blocked() -> None:
    assert is_blocked_path("/_analytics") is True
    assert is_blocked_path("/_analytics/events") is True


def test_gtm_blocked() -> None:
    assert is_blocked_path("/gtm.js") is True


def test_normal_api_not_blocked() -> None:
    assert is_blocked_path("/posts") is False
    assert is_blocked_path("/api/users") is False
    assert is_blocked_path("/v1/products") is False


def test_next_data_not_blocked() -> None:
    """/_next/data carries real app data and must NOT be blocked."""
    assert is_blocked_path("/_next/data/abc123/page.json") is False


def test_manifest_not_blocked() -> None:
    assert is_blocked_path("/manifest.json") is False


def test_empty_path_not_blocked() -> None:
    assert is_blocked_path("") is False
    assert is_blocked_path("/") is False


def test_blocklist_is_tight() -> None:
    """Blocklist should be small and specific."""
    assert len(BLOCKED_PATH_PREFIXES) <= 10
