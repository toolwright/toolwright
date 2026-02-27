"""Tests for publishing proposal artifacts into runtime-ready bundles."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.core.approval import LockfileManager

PROPOSALS_PAYLOAD = {
    "version": "1.0.0",
    "generated_at": "2026-02-13T00:00:00+00:00",
    "capture_id": "cap_publish",
    "scope": "first_party_only",
    "proposals": [
        {
            "proposal_id": "tp_query_1",
            "name": "query_recently_viewed_products",
            "kind": "graphql",
            "host": "stockx.com",
            "method": "POST",
            "path_template": "/api/graphql",
            "risk_tier": "low",
            "confidence": 0.92,
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
            "operation_type": "query",
            "rationale": ["Observed operation."],
        },
        {
            "proposal_id": "tp_mutate_1",
            "name": "mutate_update_bid",
            "kind": "graphql",
            "host": "stockx.com",
            "method": "POST",
            "path_template": "/api/graphql",
            "risk_tier": "high",
            "confidence": 0.9,
            "requires_review": True,
            "parameters": [
                {
                    "name": "variables",
                    "source": "body",
                    "required": False,
                }
            ],
            "fixed_body": {"operationName": "UpdateBid"},
            "operation_name": "UpdateBid",
            "operation_type": "mutation",
            "rationale": ["Observed operation."],
        },
        {
            "proposal_id": "tp_low_conf_1",
            "name": "get_listing_detail",
            "kind": "rest",
            "host": "stockx.com",
            "method": "GET",
            "path_template": "/en/product/{slug}.json",
            "risk_tier": "low",
            "confidence": 0.5,
            "requires_review": True,
            "parameters": [
                {
                    "name": "slug",
                    "source": "path",
                    "required": True,
                }
            ],
            "rationale": ["Needs more examples."],
        },
    ],
}


def _write_proposals(root: Path) -> Path:
    proposal_dir = root / "proposals" / "proposal_test"
    proposal_dir.mkdir(parents=True)
    payload_path = proposal_dir / "tools.proposed.yaml"
    payload_path.write_text(yaml.safe_dump(PROPOSALS_PAYLOAD, sort_keys=False), encoding="utf-8")
    return proposal_dir


def test_propose_publish_writes_bundle_with_default_filters(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    proposal_dir = _write_proposals(root)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "propose",
            "publish",
            str(proposal_dir),
        ],
    )
    assert result.exit_code == 0
    assert "Published proposal bundle" in result.output

    published_root = root / "published"
    bundles = sorted(p for p in published_root.iterdir() if p.is_dir())
    assert bundles

    latest = bundles[-1]
    tools = json.loads((latest / "tools.json").read_text(encoding="utf-8"))
    toolsets = yaml.safe_load((latest / "toolsets.yaml").read_text(encoding="utf-8"))
    policy = yaml.safe_load((latest / "policy.yaml").read_text(encoding="utf-8"))
    report = json.loads((latest / "publish_report.json").read_text(encoding="utf-8"))

    action_names = [action["name"] for action in tools["actions"]]
    assert action_names == ["query_recently_viewed_products"]
    assert toolsets["toolsets"]["readonly"]["actions"] == ["query_recently_viewed_products"]
    assert policy["state_changing_overrides"]
    assert policy["state_changing_overrides"][0]["state_changing"] is False

    assert report["selected_count"] == 1
    assert report["excluded_count"] == 2


def test_propose_publish_syncs_lockfile_when_requested(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    proposal_dir = _write_proposals(root)
    lockfile = root / "lockfile" / "stockx.lock.yaml"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "propose",
            "publish",
            str(proposal_dir),
            "--include-review-required",
            "--max-risk",
            "critical",
            "--sync-lockfile",
            "--lockfile",
            str(lockfile),
        ],
    )
    assert result.exit_code == 0
    assert "Lockfile synced" in result.output

    manager = LockfileManager(lockfile)
    loaded = manager.load()
    assert loaded.total_tools == 2
    assert loaded.pending_count == 2

    published_root = root / "published"
    bundles = sorted(p for p in published_root.iterdir() if p.is_dir())
    latest = bundles[-1]
    toolsets = yaml.safe_load((latest / "toolsets.yaml").read_text(encoding="utf-8"))
    assert "query_recently_viewed_products" in toolsets["toolsets"]["readonly"]["actions"]
    assert "mutate_update_bid" in toolsets["toolsets"]["write_ops"]["actions"]
