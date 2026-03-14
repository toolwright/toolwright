"""Tests for OpenAPI parser warning surfacing (C1).

When endpoints are skipped during parsing, the user must see warnings
and the CLI must raise if ALL endpoints are skipped.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import click
import pytest

from toolwright.core.capture.openapi_parser import OpenAPIParser


def _write_spec(tmp_path: Path, spec: dict) -> Path:
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    return p


def _minimal_spec(paths: dict | None = None) -> dict:
    """Return a minimal valid OpenAPI 3.1 spec."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": paths or {},
    }


class TestFallbackHostWarning:
    """H2: falling back to api.example.com must emit a warning."""

    def test_relative_url_emits_fallback_warning(self, tmp_path: Path) -> None:
        """Spec with relative server URL should warn about api.example.com fallback."""
        spec = {
            "openapi": "3.1.0",
            "info": {"title": "Test API", "version": "1.0"},
            "servers": [{"url": "/api/v3"}],
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "listPets",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        spec_path = _write_spec(tmp_path, spec)
        parser = OpenAPIParser()
        session = parser.parse_file(spec_path)

        assert any("api.example.com" in w for w in parser.warnings)
        assert any("--base-url" in w for w in parser.warnings)

    def test_missing_servers_emits_fallback_warning(self, tmp_path: Path) -> None:
        """Spec with no servers field should warn about api.example.com fallback."""
        spec = {
            "openapi": "3.1.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "listPets",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        spec_path = _write_spec(tmp_path, spec)
        parser = OpenAPIParser()
        session = parser.parse_file(spec_path)

        assert any("api.example.com" in w for w in parser.warnings)

    def test_valid_host_no_fallback_warning(self, tmp_path: Path) -> None:
        """Spec with valid absolute server URL should NOT warn about fallback."""
        spec = _minimal_spec({
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "responses": {"200": {"description": "ok"}},
                }
            }
        })
        spec_path = _write_spec(tmp_path, spec)
        parser = OpenAPIParser()
        session = parser.parse_file(spec_path)

        assert not any("api.example.com" in w for w in parser.warnings)


class TestSkippedEndpointWarnings:
    """C1: skipped endpoints must produce user-visible warnings."""

    def test_skipped_endpoints_recorded_in_stats(self, tmp_path: Path) -> None:
        """Parser.stats['skipped'] must count endpoints that failed _create_exchange."""
        spec = _minimal_spec({
            "/ok": {
                "get": {
                    "operationId": "getOk",
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/bad": {
                "post": {
                    "operationId": "postBad",
                    "responses": {"200": {"description": "ok"}},
                }
            },
        })
        spec_path = _write_spec(tmp_path, spec)
        parser = OpenAPIParser(allowed_hosts=["api.example.com"])

        # Force _create_exchange to fail for POST /bad
        original = parser._create_exchange

        def patched(*args, **kwargs):
            if kwargs.get("path_template") == "/bad" or (args and args[1] == "/bad"):
                raise RuntimeError("Simulated parse failure")
            return original(*args, **kwargs)

        with patch.object(parser, "_create_exchange", side_effect=patched):
            session = parser.parse_file(spec_path)

        assert parser.stats["skipped"] == 1
        assert parser.stats["imported"] == 1
        assert any("/bad" in w for w in parser.warnings)

    def test_warnings_attached_to_session(self, tmp_path: Path) -> None:
        """session.warnings must contain the skip reasons."""
        spec = _minimal_spec({
            "/ok": {
                "get": {
                    "operationId": "getOk",
                    "responses": {"200": {"description": "ok"}},
                }
            },
        })
        spec_path = _write_spec(tmp_path, spec)
        parser = OpenAPIParser(allowed_hosts=["api.example.com"])

        # Force _create_exchange to fail for everything
        with patch.object(
            parser, "_create_exchange", side_effect=RuntimeError("boom")
        ):
            session = parser.parse_file(spec_path)

        assert len(session.warnings) >= 1
        assert any("boom" in w for w in session.warnings)


class TestCommandsCreateSkippedWarning:
    """C1: run_create must warn the user about skipped endpoints."""

    def test_partial_skip_emits_warning(self, tmp_path: Path, capsys) -> None:
        """When some (but not all) endpoints are skipped, a WARNING must be printed."""
        from toolwright.cli.commands_create import run_create

        spec = _minimal_spec({
            "/ok": {
                "get": {
                    "operationId": "getOk",
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/bad": {
                "post": {
                    "operationId": "postBad",
                    "responses": {"200": {"description": "ok"}},
                }
            },
        })
        spec_path = _write_spec(tmp_path, spec)

        # Patch _create_exchange on any OpenAPIParser instance to fail on /bad
        original_create = OpenAPIParser._create_exchange

        def patched_create(self_inner, *, method, path_template, **kwargs):
            if path_template == "/bad":
                raise RuntimeError("Simulated failure on /bad")
            return original_create(
                self_inner, method=method, path_template=path_template, **kwargs
            )

        with patch.object(OpenAPIParser, "_create_exchange", patched_create):
            run_create(
                api_name=None,
                spec=str(spec_path),
                name="test",
                auto_approve=True,
                apply_rules=False,
                output_root=str(tmp_path / ".toolwright"),
                verbose=False,
            )

        captured = capsys.readouterr()
        assert "WARNING" in captured.err or "WARNING" in captured.out
        assert "skipped" in captured.err.lower() or "skipped" in captured.out.lower()

    def test_all_skipped_raises_click_exception(self, tmp_path: Path) -> None:
        """When ALL endpoints are skipped, a ClickException must be raised."""
        from toolwright.cli.commands_create import run_create

        spec = _minimal_spec({
            "/a": {
                "get": {
                    "operationId": "getA",
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/b": {
                "post": {
                    "operationId": "postB",
                    "responses": {"200": {"description": "ok"}},
                }
            },
        })
        spec_path = _write_spec(tmp_path, spec)

        with patch.object(
            OpenAPIParser, "_create_exchange", side_effect=RuntimeError("all fail")
        ):
            with pytest.raises(click.ClickException, match="skipped"):
                run_create(
                    api_name=None,
                    spec=str(spec_path),
                    name="test",
                    auto_approve=True,
                    apply_rules=False,
                    output_root=str(tmp_path / ".toolwright"),
                    verbose=False,
                )
