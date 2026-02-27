"""Tests for scopes merge command."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli


def test_scopes_merge_proposes_without_overwrite(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    scopes_dir = root / "scopes"
    scopes_dir.mkdir(parents=True, exist_ok=True)

    suggested = scopes_dir / "scopes.suggested.yaml"
    suggested.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "scopes": {
                    "search": {"intent": "search"},
                    "product_detail": {"intent": "detail"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    authoritative = scopes_dir / "scopes.yaml"
    authoritative.write_text(
        yaml.safe_dump({"version": 1, "scopes": {"search": {"intent": "user-owned"}}}, sort_keys=False),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(root), "scope", "merge"])
    assert result.exit_code == 0

    proposal = scopes_dir / "scopes.merge.proposed.yaml"
    assert proposal.exists()
    proposal_payload = yaml.safe_load(proposal.read_text(encoding="utf-8"))
    assert proposal_payload["scopes"]["search"]["intent"] == "user-owned"
    assert "product_detail" in proposal_payload["scopes"]

    authoritative_payload = yaml.safe_load(authoritative.read_text(encoding="utf-8"))
    assert authoritative_payload["scopes"]["search"]["intent"] == "user-owned"
    assert "product_detail" not in authoritative_payload["scopes"]


def test_scopes_merge_apply_updates_authoritative(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    scopes_dir = root / "scopes"
    scopes_dir.mkdir(parents=True, exist_ok=True)

    (scopes_dir / "scopes.suggested.yaml").write_text(
        yaml.safe_dump(
            {"version": 1, "scopes": {"search": {"intent": "search"}}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    authoritative = scopes_dir / "scopes.yaml"
    authoritative.write_text(yaml.safe_dump({"version": 1, "scopes": {}}, sort_keys=False), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(root), "scope", "merge", "--apply"])
    assert result.exit_code == 0

    payload = yaml.safe_load(authoritative.read_text(encoding="utf-8"))
    assert "search" in payload["scopes"]


def test_scopes_merge_supports_draft_style_suggestions(tmp_path: Path) -> None:
    root = tmp_path / ".toolwright"
    scopes_dir = root / "scopes"
    scopes_dir.mkdir(parents=True, exist_ok=True)

    (scopes_dir / "scopes.suggested.yaml").write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "scope": "first_party_only",
                "drafts": [
                    {
                        "endpoint_id": "sig_read",
                        "scope_name": "read",
                        "confidence": 0.88,
                        "risk_tier": "safe",
                        "review_required": False,
                        "signals": ["read endpoint"],
                    },
                    {
                        "endpoint_id": "sig_write",
                        "scope_name": "write",
                        "confidence": 0.71,
                        "risk_tier": "high",
                        "review_required": True,
                        "signals": ["state-changing method: POST"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    authoritative = scopes_dir / "scopes.yaml"
    authoritative.write_text(yaml.safe_dump({"version": 1, "scopes": {}}, sort_keys=False), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(root), "scope", "merge", "--apply"])
    assert result.exit_code == 0

    payload = yaml.safe_load(authoritative.read_text(encoding="utf-8"))
    assert "read" in payload["scopes"]
    assert "write" in payload["scopes"]
    assert payload["scopes"]["write"]["review_required"] is True
    assert payload["scopes"]["write"]["risk_tier"] == "high"
