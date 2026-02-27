"""Tests for OpenAPI parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from toolwright.core.capture.openapi_parser import OpenAPIParser


@pytest.fixture
def simple_openapi_spec() -> dict:
    """Simple OpenAPI 3.0 specification."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Test API",
            "version": "1.0.0",
            "description": "A test API for unit tests",
        },
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "summary": "List all users",
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/User"},
                                    }
                                }
                            },
                        }
                    },
                },
                "post": {
                    "operationId": "createUser",
                    "summary": "Create a user",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/User"}
                            }
                        }
                    },
                    "responses": {"201": {"description": "Created"}},
                },
            },
            "/users/{id}": {
                "get": {
                    "operationId": "getUser",
                    "summary": "Get user by ID",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "Success"}},
                },
                "delete": {
                    "operationId": "deleteUser",
                    "summary": "Delete user",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"204": {"description": "Deleted"}},
                },
            },
        },
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "email": {"type": "string", "format": "email"},
                    },
                }
            }
        },
    }


@pytest.fixture
def openapi_json_file(tmp_path: Path, simple_openapi_spec: dict) -> Path:
    """Create a temporary OpenAPI JSON file."""
    path = tmp_path / "api.json"
    with open(path, "w") as f:
        json.dump(simple_openapi_spec, f)
    return path


@pytest.fixture
def openapi_yaml_file(tmp_path: Path, simple_openapi_spec: dict) -> Path:
    """Create a temporary OpenAPI YAML file."""
    path = tmp_path / "api.yaml"
    with open(path, "w") as f:
        yaml.dump(simple_openapi_spec, f)
    return path


class TestOpenAPIParser:
    """Tests for OpenAPIParser."""

    def test_parse_json_file(self, openapi_json_file: Path) -> None:
        """Test parsing a JSON OpenAPI file."""
        parser = OpenAPIParser()
        session = parser.parse_file(openapi_json_file)

        assert session.name == "Test API"
        assert len(session.exchanges) == 4  # GET /users, POST /users, GET /users/{id}, DELETE /users/{id}

    def test_parse_yaml_file(self, openapi_yaml_file: Path) -> None:
        """Test parsing a YAML OpenAPI file."""
        parser = OpenAPIParser()
        session = parser.parse_file(openapi_yaml_file)

        assert session.name == "Test API"
        assert len(session.exchanges) == 4

    def test_extracts_host_from_servers(self, openapi_json_file: Path) -> None:
        """Test that host is extracted from servers."""
        parser = OpenAPIParser()
        session = parser.parse_file(openapi_json_file)

        # All exchanges should have the correct host
        for exchange in session.exchanges:
            assert exchange.host == "api.example.com"

    def test_extracts_methods(self, openapi_json_file: Path) -> None:
        """Test that HTTP methods are correctly extracted."""
        parser = OpenAPIParser()
        session = parser.parse_file(openapi_json_file)

        methods = {e.method for e in session.exchanges}
        assert "GET" in methods
        assert "POST" in methods
        assert "DELETE" in methods

    def test_extracts_paths(self, openapi_json_file: Path) -> None:
        """Test that paths are correctly extracted."""
        parser = OpenAPIParser()
        session = parser.parse_file(openapi_json_file)

        paths = {e.path for e in session.exchanges}
        assert "/users" in paths
        assert "/users/{id}" in paths

    def test_extracts_operation_metadata(self, openapi_json_file: Path) -> None:
        """Test that operation metadata is captured in notes."""
        parser = OpenAPIParser()
        session = parser.parse_file(openapi_json_file)

        # Find the listUsers operation
        list_users = next(
            (e for e in session.exchanges if e.notes.get("openapi_operation_id") == "listUsers"),
            None,
        )
        assert list_users is not None
        assert list_users.notes["openapi_summary"] == "List all users"

    def test_resolves_schema_refs(self, openapi_json_file: Path) -> None:
        """Test that $ref schemas are resolved."""
        parser = OpenAPIParser()
        session = parser.parse_file(openapi_json_file)

        # Find POST /users which has a request body with $ref
        post_users = next(
            (e for e in session.exchanges if e.method == "POST" and e.path == "/users"),
            None,
        )
        assert post_users is not None
        assert post_users.request_body_json is not None
        # Should have resolved the User schema
        assert "id" in post_users.request_body_json
        assert "name" in post_users.request_body_json

    def test_custom_allowed_hosts(self, openapi_json_file: Path) -> None:
        """Test that custom allowed hosts can be specified."""
        parser = OpenAPIParser(allowed_hosts=["custom.api.com"])
        session = parser.parse_file(openapi_json_file)

        assert "custom.api.com" in session.allowed_hosts

    def test_stats_tracking(self, openapi_json_file: Path) -> None:
        """Test that parsing stats are tracked."""
        parser = OpenAPIParser()
        parser.parse_file(openapi_json_file)

        assert parser.stats["total_paths"] == 2
        assert parser.stats["total_operations"] == 4
        assert parser.stats["imported"] == 4
        assert parser.stats["skipped"] == 0

    def test_swagger_2_rejected(self, tmp_path: Path) -> None:
        """Test that Swagger 2.0 specs are rejected."""
        spec = {"swagger": "2.0", "info": {"title": "Test"}, "paths": {}}
        path = tmp_path / "swagger.json"
        with open(path, "w") as f:
            json.dump(spec, f)

        parser = OpenAPIParser()
        with pytest.raises(ValueError, match="Swagger 2.0 is not supported"):
            parser.parse_file(path)

    def test_missing_version_rejected(self, tmp_path: Path) -> None:
        """Test that specs without version are rejected."""
        spec = {"info": {"title": "Test"}, "paths": {}}
        path = tmp_path / "invalid.json"
        with open(path, "w") as f:
            json.dump(spec, f)

        parser = OpenAPIParser()
        with pytest.raises(ValueError, match="Missing 'openapi' version"):
            parser.parse_file(path)

    def test_relative_server_uses_allowed_host_for_exchange(self, tmp_path: Path) -> None:
        """When server URLs are relative, explicit allowed hosts should drive exchange host."""
        spec = {
            "openapi": "3.0.3",
            "info": {"title": "Relative API", "version": "1.0.0"},
            "servers": [{"url": "/api/v1"}],
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        path = tmp_path / "relative.json"
        path.write_text(json.dumps(spec), encoding="utf-8")

        parser = OpenAPIParser(allowed_hosts=["shop.example.com"])
        session = parser.parse_file(path)

        assert session.allowed_hosts == ["shop.example.com"]
        assert len(session.exchanges) == 1
        assert session.exchanges[0].host == "shop.example.com"

    def test_relative_server_defaults_allowed_hosts_to_synthetic_exchange_host(self, tmp_path: Path) -> None:
        """Relative server specs without allowed hosts should still produce compile-safe first-party hosts."""
        spec = {
            "openapi": "3.0.3",
            "info": {"title": "Relative API", "version": "1.0.0"},
            "servers": [{"url": "/api/v1"}],
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        path = tmp_path / "relative-defaults.json"
        path.write_text(json.dumps(spec), encoding="utf-8")

        parser = OpenAPIParser()
        session = parser.parse_file(path)

        assert len(session.exchanges) == 1
        assert session.exchanges[0].host == "api.example.com"
        assert session.allowed_hosts == ["api.example.com"]


class TestSchemaToExample:
    """Tests for schema to example conversion."""

    def test_string_types(self, tmp_path: Path) -> None:
        """Test default values for string types."""
        spec = {
            "openapi": "3.0.3",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "email": {"type": "string", "format": "email"},
                                            "date": {"type": "string", "format": "date"},
                                            "datetime": {"type": "string", "format": "date-time"},
                                            "uri": {"type": "string", "format": "uri"},
                                            "uuid": {"type": "string", "format": "uuid"},
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        path = tmp_path / "test.json"
        with open(path, "w") as f:
            json.dump(spec, f)

        parser = OpenAPIParser()
        session = parser.parse_file(path)

        assert len(session.exchanges) == 1
        body = session.exchanges[0].request_body_json
        assert body is not None
        assert body["email"] == "user@example.com"
        assert body["date"] == "2024-01-01"
        assert body["datetime"] == "2024-01-01T00:00:00Z"
        assert body["uri"] == "https://example.com"

    def test_uses_example_values(self, tmp_path: Path) -> None:
        """Test that example values from schema are used."""
        spec = {
            "openapi": "3.0.3",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {
                                                "type": "string",
                                                "example": "John Doe",
                                            },
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        path = tmp_path / "test.json"
        with open(path, "w") as f:
            json.dump(spec, f)

        parser = OpenAPIParser()
        session = parser.parse_file(path)

        body = session.exchanges[0].request_body_json
        assert body is not None
        assert body["name"] == "John Doe"


class TestOpenAPICLI:
    """Tests for OpenAPI CLI command."""

    def test_cli_import(self, openapi_json_file: Path, tmp_path: Path) -> None:
        """Test CLI openapi import command."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        output_dir = tmp_path / ".toolwright" / "captures"

        result = runner.invoke(
            cli,
            [
                "capture",
                "import",
                "--input-format",
                "openapi",
                str(openapi_json_file),
                "-a",
                "api.example.com",
                "--output",
                str(output_dir),
                "--name",
                "CLI Test",
            ],
        )

        assert result.exit_code == 0
        assert "Capture saved:" in result.output
        assert "Operations: 4" in result.output

    def test_cli_import_with_verbose(self, openapi_json_file: Path, tmp_path: Path) -> None:
        """Test CLI openapi import with verbose output."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        output_dir = tmp_path / ".toolwright" / "captures"

        result = runner.invoke(
            cli,
            [
                "-v",
                "capture",
                "import",
                "--input-format",
                "openapi",
                str(openapi_json_file),
                "-a",
                "api.example.com",
                "--output",
                str(output_dir),
            ],
        )

        assert result.exit_code == 0
        assert "Import stats:" in result.output
        assert "Paths:" in result.output

    def test_cli_import_url(self, simple_openapi_spec: dict, tmp_path: Path) -> None:
        """Test CLI openapi import from URL (F-003)."""
        from unittest.mock import patch
        from click.testing import CliRunner
        from toolwright.cli.main import cli

        spec_json = json.dumps(simple_openapi_spec).encode("utf-8")

        # Mock urllib.request.urlopen to return our spec
        import io
        mock_response = io.BytesIO(spec_json)
        mock_response.headers = {"Content-Type": "application/json"}  # type: ignore

        runner = CliRunner()
        output_dir = tmp_path / ".toolwright" / "captures"

        with patch("toolwright.cli.capture.urlopen", return_value=mock_response):
            result = runner.invoke(
                cli,
                [
                    "capture",
                    "import",
                    "--input-format",
                    "openapi",
                    "https://api.example.com/openapi.json",
                    "-a",
                    "api.example.com",
                    "--output",
                    str(output_dir),
                    "--name",
                    "URL Test",
                ],
            )

        assert result.exit_code == 0, f"Import failed: {result.output}"
        assert "Capture saved:" in result.output
        assert "Operations:" in result.output
