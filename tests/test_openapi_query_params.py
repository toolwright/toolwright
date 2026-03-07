"""Tests for OpenAPI query parameter compilation (F-019).

The OpenAPI parser should include query parameters in the synthetic exchange URL
so the normalize/compile pipeline sees them and exposes them as tool inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.core.capture.openapi_parser import OpenAPIParser


def _minimal_spec_with_query_params() -> dict:
    """An OpenAPI spec with a GET endpoint that has query parameters."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/search/repositories": {
                "get": {
                    "operationId": "searchRepositories",
                    "summary": "Search repositories",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Search query",
                        },
                        {
                            "name": "per_page",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 30},
                            "description": "Results per page",
                        },
                        {
                            "name": "page",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 1},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "items": {"type": "array"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


def test_openapi_parser_includes_query_params_in_exchange_url(
    tmp_path: Path,
) -> None:
    """Query parameters from the OpenAPI spec should appear in the exchange URL."""
    spec = _minimal_spec_with_query_params()
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    parser = OpenAPIParser(allowed_hosts=["api.example.com"])
    session = parser.parse_file(spec_file)

    assert len(session.exchanges) == 1
    exchange = session.exchanges[0]

    # The URL should contain query parameters
    assert "?" in exchange.url
    assert "q=" in exchange.url
    assert "per_page=" in exchange.url
    assert "page=" in exchange.url


def test_openapi_parser_preserves_path_params_alongside_query_params(
    tmp_path: Path,
) -> None:
    """Path params and query params should coexist properly."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/repos/{owner}/{repo}/issues": {
                "get": {
                    "operationId": "listIssues",
                    "parameters": [
                        {"name": "owner", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "repo", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "state", "in": "query", "schema": {"type": "string", "default": "open"}},
                        {"name": "labels", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    parser = OpenAPIParser(allowed_hosts=["api.example.com"])
    session = parser.parse_file(spec_file)

    assert len(session.exchanges) == 1
    exchange = session.exchanges[0]

    # Path template should have placeholders
    assert "{owner}" in exchange.path
    assert "{repo}" in exchange.path

    # URL should include query params
    assert "state=" in exchange.url
    assert "labels=" in exchange.url
