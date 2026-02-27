"""CLI tests for catalog-driven proposal generation."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod
from toolwright.storage import Storage


def _seed_capture(root: Path) -> CaptureSession:
    session = CaptureSession(
        id="cap_cli_propose",
        name="cli-propose",
        allowed_hosts=["stockx.com"],
        exchanges=[
            HttpExchange(
                id="e1",
                url="https://stockx.com/_next/data/fz5n7pu8ao27rmx9abcde12345/en/buy/air-jordan-4-retro-rare-air-white-lettering.json",
                method=HTTPMethod.GET,
                host="stockx.com",
                path="/_next/data/fz5n7pu8ao27rmx9abcde12345/en/buy/air-jordan-4-retro-rare-air-white-lettering.json",
                response_status=200,
                response_headers={"Content-Type": "application/json"},
                response_body_json={"pageProps": {"slug": "air-jordan-4-retro-rare-air-white-lettering"}},
            ),
            HttpExchange(
                id="e2",
                url="https://stockx.com/api/graphql",
                method=HTTPMethod.POST,
                host="stockx.com",
                path="/api/graphql",
                request_headers={"Content-Type": "application/json"},
                request_body_json={
                    "operationName": "RecentlyViewedProducts",
                    "variables": {"slug": "air-jordan-4-retro-rare-air-white-lettering"},
                },
                response_status=200,
                response_headers={"Content-Type": "application/json"},
                response_body_json={"data": {"viewer": {"id": "user_1"}}},
            ),
        ],
    )
    Storage(base_path=root).save_capture(session)
    return session


def test_propose_from_capture_writes_artifacts(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    session = _seed_capture(root)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--root", str(root), "propose", "create", session.id, "--scope", "first_party_only"],
    )
    assert result.exit_code == 0
    assert "endpoint_catalog.yaml" in result.output
    assert "tools.proposed.yaml" in result.output
    assert "questions.yaml" in result.output

    proposals_root = root / "proposals"
    assert proposals_root.exists()
    output_dirs = sorted([p for p in proposals_root.iterdir() if p.is_dir()])
    assert output_dirs

    latest = output_dirs[-1]
    endpoint_catalog = latest / "endpoint_catalog.yaml"
    tools_proposed = latest / "tools.proposed.yaml"
    questions = latest / "questions.yaml"
    assert endpoint_catalog.exists()
    assert tools_proposed.exists()
    assert questions.exists()

    catalog_payload = yaml.safe_load(endpoint_catalog.read_text(encoding="utf-8"))
    tools_payload = yaml.safe_load(tools_proposed.read_text(encoding="utf-8"))
    questions_payload = yaml.safe_load(questions.read_text(encoding="utf-8"))

    assert catalog_payload["capture_id"] == session.id
    assert "families" in catalog_payload and catalog_payload["families"]
    assert "proposals" in tools_payload and tools_payload["proposals"]
    assert "questions" in questions_payload

    proposal_names = {p["name"] for p in tools_payload["proposals"]}
    assert "query_recently_viewed_products" in proposal_names
