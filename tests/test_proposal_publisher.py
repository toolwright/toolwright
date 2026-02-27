"""Tests for proposal publishing internals."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from toolwright.core.proposal.publisher import ProposalPublisher


def _write_payload(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_publish_infers_query_type_and_adds_state_override(tmp_path: Path) -> None:
    payload = {
        "version": "1.0.0",
        "generated_at": "2026-02-13T00:00:00+00:00",
        "capture_id": "cap_query_infer",
        "scope": "first_party_only",
        "proposals": [
            {
                "proposal_id": "tp_1",
                "name": "query_recently_viewed_products",
                "kind": "graphql",
                "host": "stockx.com",
                "method": "POST",
                "path_template": "/api/graphql",
                "risk_tier": "medium",
                "confidence": 0.9,
                "requires_review": False,
                "parameters": [
                    {
                        "name": "variables",
                        "source": "body",
                        "required": False,
                    }
                ],
                "fixed_body": {"operationName": "RecentlyViewedProducts"},
                "operation_name": "RecentlyViewedProducts",
                "operation_type": "unknown",
            }
        ],
    }

    proposals_path = _write_payload(tmp_path / "tools.proposed.yaml", payload)
    result = ProposalPublisher().publish(
        proposals_path=proposals_path,
        output_root=tmp_path / "published",
        min_confidence=0.75,
        max_risk="high",
        include_review_required=False,
        proposal_ids=(),
        deterministic=True,
    )

    tools = json.loads(result.tools_path.read_text(encoding="utf-8"))
    policy = yaml.safe_load(result.policy_path.read_text(encoding="utf-8"))

    action = tools["actions"][0]
    assert action["graphql_operation_type"] == "query"
    assert "graphql:query" in action["tags"]

    overrides = policy["state_changing_overrides"]
    assert len(overrides) == 1
    assert overrides[0]["state_changing"] is False


def test_publish_promotes_stable_graphql_query_to_fixed_body(tmp_path: Path) -> None:
    payload = {
        "version": "1.0.0",
        "generated_at": "2026-02-13T00:00:00+00:00",
        "capture_id": "cap_query_fixed",
        "scope": "first_party_only",
        "proposals": [
            {
                "proposal_id": "tp_1",
                "name": "query_product",
                "kind": "graphql",
                "host": "stockx.com",
                "method": "POST",
                "path_template": "/api/graphql",
                "risk_tier": "low",
                "confidence": 0.9,
                "requires_review": False,
                "parameters": [
                    {
                        "name": "query",
                        "source": "body",
                        "required": True,
                        "default": "query Product($slug: String!) { product(slug: $slug) { id } }",
                    },
                    {
                        "name": "variables",
                        "source": "body",
                        "required": True,
                    },
                ],
                "fixed_body": {"operationName": "Product"},
                "operation_name": "Product",
                "operation_type": "query",
            }
        ],
    }

    proposals_path = _write_payload(tmp_path / "tools.proposed.yaml", payload)
    result = ProposalPublisher().publish(
        proposals_path=proposals_path,
        output_root=tmp_path / "published",
        min_confidence=0.75,
        max_risk="high",
        include_review_required=False,
        proposal_ids=(),
        deterministic=True,
    )

    tools = json.loads(result.tools_path.read_text(encoding="utf-8"))
    action = tools["actions"][0]

    assert action["fixed_body"]["query"].startswith("query Product")
    required = set(action["input_schema"].get("required", []))
    assert "variables" in required
    assert "query" not in required
