"""Tests for LLM-assisted enrichment (optional post-compile pass)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from toolwright.core.enrich.llm_classifier import LLMEnricher
from toolwright.models.endpoint import Endpoint


def _ep(
    method: str = "GET",
    path: str = "/api/v1/items",
    tags: list[str] | None = None,
    response_body_schema: dict | None = None,
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host="api.example.com",
        url=f"https://api.example.com{path}",
        tags=tags or [],
        response_body_schema=response_body_schema,
    )


class TestLLMEnricherInit:
    """Test LLMEnricher initialization."""

    def test_requires_endpoint(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        assert enricher.endpoint == "https://api.example.com/v1/chat"

    def test_optional_api_key(self):
        enricher = LLMEnricher(
            endpoint="https://api.example.com/v1/chat",
            api_key="sk-test",
        )
        assert enricher.api_key == "sk-test"

    def test_default_model(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        assert enricher.model is not None


class TestLLMEnricherPrompt:
    """Test prompt generation for LLM enrichment."""

    def test_builds_prompt_from_endpoint(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        ep = _ep(
            method="GET",
            path="/api/v1/products",
            tags=["products", "read", "commerce"],
            response_body_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
            },
        )
        prompt = enricher.build_prompt(ep)
        assert "GET" in prompt
        assert "/api/v1/products" in prompt
        assert "commerce" in prompt

    def test_prompt_includes_schema(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        ep = _ep(
            response_body_schema={
                "type": "object",
                "properties": {"price": {"type": "number"}},
            },
        )
        prompt = enricher.build_prompt(ep)
        assert "price" in prompt


class TestLLMEnricherParsing:
    """Test parsing LLM responses into enrichment data."""

    def test_parse_valid_json_response(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        raw = '{"tags": ["commerce", "inventory"], "description": "List inventory items", "when_to_use": "When you need to browse available products"}'
        result = enricher.parse_response(raw)
        assert "tags" in result
        assert "commerce" in result["tags"]
        assert "description" in result

    def test_parse_invalid_json_returns_empty(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        result = enricher.parse_response("not json at all")
        assert result == {}

    def test_parse_json_missing_fields_returns_partial(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        result = enricher.parse_response('{"tags": ["test"]}')
        assert "tags" in result
        assert "description" not in result


class TestLLMEnricherApply:
    """Test applying LLM enrichment to endpoints."""

    def test_apply_merges_tags(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        ep = _ep(tags=["read", "commerce"])
        enrichment = {"tags": ["inventory", "commerce"]}
        enricher.apply_enrichment(ep, enrichment)
        assert "inventory" in ep.tags
        assert "commerce" in ep.tags
        assert "read" in ep.tags
        # No duplicates
        assert len(ep.tags) == len(set(ep.tags))

    def test_apply_empty_enrichment_no_change(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        ep = _ep(tags=["read"])
        original_tags = list(ep.tags)
        enricher.apply_enrichment(ep, {})
        assert ep.tags == original_tags


@pytest.mark.asyncio
class TestLLMEnricherHTTP:
    """Test the HTTP call to the LLM endpoint (mocked)."""

    async def test_enrich_endpoint_calls_api(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        ep = _ep(path="/api/v1/orders", tags=["orders", "read"])

        response_data = {
            "choices": [
                {
                    "message": {
                        "content": '{"tags": ["commerce"], "description": "List orders", "when_to_use": "Browse order history"}'
                    }
                }
            ]
        }

        mock_response = AsyncMock()
        mock_response.status_code = 200
        # .json() is a regular method on httpx.Response, not async
        mock_response.json = lambda: response_data

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await enricher.enrich_endpoint(ep)
            assert "tags" in result
            assert "commerce" in result["tags"]

    async def test_enrich_endpoint_handles_api_error(self):
        enricher = LLMEnricher(endpoint="https://api.example.com/v1/chat")
        ep = _ep(path="/api/v1/orders")

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await enricher.enrich_endpoint(ep)
            assert result == {}
