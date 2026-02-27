"""Tests for CORS preflight (OPTIONS) filtering.

OPTIONS requests are CORS preflights and should not become tool endpoints.
They produce tools with no parameters, confusing users capturing SPAs.
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
) -> dict:
    """Create a HAR entry."""
    return {
        "request": {
            "method": method,
            "url": url,
            "headers": [],
        },
        "response": {
            "status": status,
            "headers": [{"name": "content-type", "value": content_type}],
            "content": {},
        },
        "_resourceType": resource_type,
    }


class TestOptionsFiltering:
    """OPTIONS requests should be filtered out during HAR parsing."""

    def test_options_requests_are_filtered(self):
        """OPTIONS entries should not produce exchanges."""
        har_path = create_har_file([
            make_entry("https://api.example.com/users", method="OPTIONS"),
            make_entry("https://api.example.com/products", method="OPTIONS"),
            make_entry("https://api.example.com/users", method="GET"),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        methods = [ex.method.value for ex in session.exchanges]
        assert "OPTIONS" not in methods
        assert "GET" in methods
        assert len(session.exchanges) == 1

    def test_options_filtered_count_tracked(self):
        """Filtered OPTIONS entries should be counted in stats."""
        har_path = create_har_file([
            make_entry("https://api.example.com/users", method="OPTIONS"),
            make_entry("https://api.example.com/products", method="OPTIONS"),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        parser.parse_file(har_path)

        # OPTIONS should be counted in filtered stats
        assert parser.stats.get("filtered_options", 0) >= 2

    def test_options_mixed_with_valid_methods(self):
        """OPTIONS should be filtered even when mixed with valid methods on the same path."""
        har_path = create_har_file([
            make_entry("https://api.example.com/api/users", method="OPTIONS"),
            make_entry("https://api.example.com/api/users", method="GET"),
            make_entry("https://api.example.com/api/users", method="POST",
                       content_type="application/json"),
        ])

        parser = HARParser(allowed_hosts=["api.example.com"])
        session = parser.parse_file(har_path)

        methods = sorted([ex.method.value for ex in session.exchanges])
        assert "OPTIONS" not in methods
        assert "GET" in methods
        assert "POST" in methods
