"""Tests for OpenAPI type, enum, and required field preservation through the compile pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolwright.core.capture.openapi_parser import OpenAPIParser


PETSTORE_SPEC = """\
openapi: "3.0.0"
info:
  title: Petstore
  version: "1.0"
servers:
  - url: https://petstore.example.com/v1
paths:
  /pets:
    get:
      operationId: listPets
      summary: List all pets
      parameters:
        - name: limit
          in: query
          required: false
          schema:
            type: integer
            minimum: 1
            maximum: 100
        - name: species
          in: query
          required: false
          schema:
            type: string
            enum: [dog, cat, bird]
        - name: vaccinated
          in: query
          required: false
          schema:
            type: boolean
      responses:
        "200":
          description: A list of pets
    post:
      operationId: createPet
      summary: Create a pet
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [name]
              properties:
                name:
                  type: string
                species:
                  type: string
                  enum: [dog, cat, bird]
                age:
                  type: integer
                vaccinated:
                  type: boolean
      responses:
        "201":
          description: Pet created
  /pets/{petId}:
    get:
      operationId: getPet
      summary: Get a pet by ID
      parameters:
        - name: petId
          in: path
          required: true
          schema:
            type: integer
      responses:
        "200":
          description: A pet
"""


@pytest.fixture
def petstore_spec(tmp_path: Path) -> Path:
    spec_path = tmp_path / "petstore.yaml"
    spec_path.write_text(PETSTORE_SPEC)
    return spec_path


class TestOpenAPIParameterSchemaPreservation:
    """Test that OpenAPI parameter schemas are stored in exchange notes."""

    def test_query_param_schemas_stored_in_notes(self, petstore_spec: Path) -> None:
        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)

        # Find the GET /pets exchange
        get_pets = [e for e in session.exchanges if e.method == "GET" and "/pets" in e.path and "{petId}" not in e.path]
        assert len(get_pets) == 1

        exchange = get_pets[0]
        param_schemas = exchange.notes.get("openapi_parameter_schemas", {})

        # Integer type should be preserved
        assert "limit" in param_schemas
        assert param_schemas["limit"]["type"] == "integer"

        # Boolean type should be preserved
        assert "vaccinated" in param_schemas
        assert param_schemas["vaccinated"]["type"] == "boolean"

        # Enum should be preserved
        assert "species" in param_schemas
        assert param_schemas["species"].get("enum") == ["dog", "cat", "bird"]

    def test_path_param_schemas_stored_in_notes(self, petstore_spec: Path) -> None:
        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)

        get_pet = [e for e in session.exchanges if "petId" in e.path]
        assert len(get_pet) == 1

        param_schemas = get_pet[0].notes.get("openapi_parameter_schemas", {})
        assert "petId" in param_schemas
        assert param_schemas["petId"]["type"] == "integer"

    def test_request_body_required_fields_stored_in_notes(self, petstore_spec: Path) -> None:
        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)

        post_pets = [e for e in session.exchanges if e.method == "POST"]
        assert len(post_pets) == 1

        exchange = post_pets[0]
        body_meta = exchange.notes.get("openapi_request_body_meta", {})
        assert body_meta.get("required_fields") == ["name"]

    def test_request_body_field_schemas_stored_in_notes(self, petstore_spec: Path) -> None:
        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)

        post_pets = [e for e in session.exchanges if e.method == "POST"]
        assert len(post_pets) == 1

        body_meta = post_pets[0].notes.get("openapi_request_body_meta", {})
        field_schemas = body_meta.get("field_schemas", {})

        assert field_schemas.get("age", {}).get("type") == "integer"
        assert field_schemas.get("vaccinated", {}).get("type") == "boolean"
        assert field_schemas.get("species", {}).get("enum") == ["dog", "cat", "bird"]


class TestCompiledOutputPreservesTypes:
    """Test that compiled tools.json preserves OpenAPI types and constraints."""

    def test_enum_in_compiled_manifest(self, petstore_spec: Path) -> None:
        """Enum constraints should appear in compiled tool input schema."""
        from toolwright.core.compile.tools import ToolManifestGenerator
        from toolwright.core.normalize.aggregator import EndpointAggregator

        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)
        aggregator = EndpointAggregator()
        endpoints = aggregator.aggregate(session)

        generator = ToolManifestGenerator()
        manifest = generator.generate(endpoints)
        actions = manifest.get("actions", [])

        # Find the GET /pets action (list_pets)
        list_pets = [a for a in actions if "list" in a.get("name", "").lower() or
                     (a.get("method") == "GET" and "/pets" in a.get("path", "") and "{" not in a.get("path", ""))]
        assert len(list_pets) >= 1, f"Could not find list_pets action in {[a['name'] for a in actions]}"

        input_schema = list_pets[0].get("input_schema", {})
        species_prop = input_schema.get("properties", {}).get("species", {})
        assert species_prop.get("enum") == ["dog", "cat", "bird"], f"species prop: {species_prop}"

    def test_integer_type_in_compiled_manifest(self, petstore_spec: Path) -> None:
        from toolwright.core.compile.tools import ToolManifestGenerator
        from toolwright.core.normalize.aggregator import EndpointAggregator

        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)
        aggregator = EndpointAggregator()
        endpoints = aggregator.aggregate(session)

        generator = ToolManifestGenerator()
        manifest = generator.generate(endpoints)
        actions = manifest.get("actions", [])

        list_pets = [a for a in actions if "list" in a.get("name", "").lower() or
                     (a.get("method") == "GET" and "/pets" in a.get("path", "") and "{" not in a.get("path", ""))]
        assert len(list_pets) >= 1

        input_schema = list_pets[0].get("input_schema", {})
        limit_prop = input_schema.get("properties", {}).get("limit", {})
        assert limit_prop.get("type") == "integer", f"limit prop: {limit_prop}"


class TestAggregatorUsesOpenAPIMetadata:
    """Test that the aggregator uses OpenAPI metadata when available."""

    def test_integer_query_params_compile_as_integer(self, petstore_spec: Path) -> None:
        """End-to-end: integer query params should have type=integer in compiled output."""
        from toolwright.core.normalize.aggregator import EndpointAggregator

        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)
        aggregator = EndpointAggregator()
        endpoints = aggregator.aggregate(session)

        get_pets = [e for e in endpoints if e.method == "GET" and "{petId}" not in e.path]
        assert len(get_pets) == 1

        params = {p.name: p for p in get_pets[0].parameters}
        assert params["limit"].param_type == "integer"

    def test_boolean_query_params_compile_as_boolean(self, petstore_spec: Path) -> None:
        from toolwright.core.normalize.aggregator import EndpointAggregator

        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)
        aggregator = EndpointAggregator()
        endpoints = aggregator.aggregate(session)

        get_pets = [e for e in endpoints if e.method == "GET" and "{petId}" not in e.path]
        assert len(get_pets) == 1

        params = {p.name: p for p in get_pets[0].parameters}
        assert params["vaccinated"].param_type == "boolean"

    def test_enum_preserved_in_parameter_schema(self, petstore_spec: Path) -> None:
        from toolwright.core.normalize.aggregator import EndpointAggregator

        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)
        aggregator = EndpointAggregator()
        endpoints = aggregator.aggregate(session)

        get_pets = [e for e in endpoints if e.method == "GET" and "{petId}" not in e.path]
        params = {p.name: p for p in get_pets[0].parameters}
        assert params["species"].json_schema is not None
        assert params["species"].json_schema.get("enum") == ["dog", "cat", "bird"]

    def test_optional_body_fields_not_required(self, petstore_spec: Path) -> None:
        """Optional request body fields should NOT be marked as required."""
        from toolwright.core.normalize.aggregator import EndpointAggregator

        parser = OpenAPIParser()
        session = parser.parse_file(petstore_spec)
        aggregator = EndpointAggregator()
        endpoints = aggregator.aggregate(session)

        post_pets = [e for e in endpoints if e.method == "POST"]
        assert len(post_pets) == 1

        body_schema = post_pets[0].request_body_schema
        assert body_schema is not None
        required = body_schema.get("required", [])
        assert "name" in required
        assert "age" not in required
        assert "vaccinated" not in required
        assert "species" not in required
