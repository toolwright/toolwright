"""Optional LLM-assisted enrichment for endpoint classification.

Sends endpoint schemas to a user-configured LLM endpoint (OpenAI-compatible)
and returns richer tags, descriptions, and "when to use" guidance.

No LLM SDK dependency -- uses httpx directly.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from toolwright.models.endpoint import Endpoint

logger = logging.getLogger(__name__)


class LLMEnricher:
    """Post-compile enrichment pass using an LLM endpoint."""

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        timeout: float = 30.0,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def build_prompt(self, ep: Endpoint) -> str:
        """Build an LLM prompt from an endpoint's metadata."""
        schema_str = ""
        if ep.response_body_schema:
            schema_str = f"\nResponse schema: {json.dumps(ep.response_body_schema, indent=2)}"
        if ep.request_body_schema:
            schema_str += f"\nRequest schema: {json.dumps(ep.request_body_schema, indent=2)}"

        tags_str = ", ".join(ep.tags) if ep.tags else "none"

        return (
            f"Classify this API endpoint and provide enrichment.\n\n"
            f"Method: {ep.method}\n"
            f"Path: {ep.path}\n"
            f"Current tags: {tags_str}\n"
            f"{schema_str}\n\n"
            f"Respond with a JSON object containing:\n"
            f'- "tags": list of semantic tags (e.g., "commerce", "users", "auth")\n'
            f'- "description": a clear 1-sentence description of what this endpoint does\n'
            f'- "when_to_use": a brief guidance on when an agent should call this\n\n'
            f"Respond ONLY with the JSON object, no markdown or explanation."
        )

    def parse_response(self, raw: str) -> dict[str, Any]:
        """Parse an LLM response into enrichment data.

        Returns a dict with optional keys: tags, description, when_to_use.
        Returns empty dict on parse failure.
        """
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}
            # Only keep recognized keys
            result: dict[str, Any] = {}
            if "tags" in data and isinstance(data["tags"], list):
                result["tags"] = [str(t) for t in data["tags"]]
            if "description" in data and isinstance(data["description"], str):
                result["description"] = data["description"]
            if "when_to_use" in data and isinstance(data["when_to_use"], str):
                result["when_to_use"] = data["when_to_use"]
            return result
        except (json.JSONDecodeError, TypeError):
            return {}

    def apply_enrichment(
        self, ep: Endpoint, enrichment: dict[str, Any]
    ) -> None:
        """Apply LLM enrichment data to an endpoint in place."""
        if not enrichment:
            return

        # Merge tags without duplicates
        if "tags" in enrichment:
            existing = set(ep.tags)
            for tag in enrichment["tags"]:
                if tag not in existing:
                    ep.tags.append(tag)
                    existing.add(tag)

    async def enrich_endpoint(self, ep: Endpoint) -> dict[str, Any]:
        """Call the LLM endpoint and return enrichment data.

        Returns empty dict on any error.
        """
        prompt = self.build_prompt(ep)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                )
                if response.status_code != 200:
                    logger.warning(
                        "LLM enrichment failed with status %d: %s",
                        response.status_code,
                        response.text,
                    )
                    return {}

                data = response.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                return self.parse_response(content)
        except Exception:
            logger.exception("LLM enrichment request failed")
            return {}
