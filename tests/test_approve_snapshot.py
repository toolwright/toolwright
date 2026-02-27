"""Tests for approval snapshot materialization."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.core.approval import LockfileManager
from toolwright.core.enforce import ConfirmationStore, DecisionEngine
from toolwright.models.decision import DecisionContext
from tests.helpers import load_yaml, write_demo_toolpack


def test_approve_materializes_snapshot(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["gate", "allow", "--all", "--lockfile", str(lockfile_path)],
    )

    assert result.exit_code == 0
    lockfile = load_yaml(lockfile_path)
    assert "baseline_snapshot_dir" in lockfile
    assert "baseline_snapshot_digest" in lockfile

    snapshot_dir = toolpack_file.parent / lockfile["baseline_snapshot_dir"]
    assert snapshot_dir.exists()
    digests_path = snapshot_dir.parent / "digests.json"
    assert digests_path.exists()


def test_approve_promotes_pending_lockfile(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    pending_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
    approved_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.yaml"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["gate", "allow", "--all", "--lockfile", str(pending_lockfile)],
    )

    assert result.exit_code == 0
    assert approved_lockfile.exists()

    toolpack = load_yaml(toolpack_file)
    assert toolpack["paths"]["lockfiles"]["approved"] == "lockfile/toolwright.lock.yaml"

    pending_payload = load_yaml(pending_lockfile)
    approved_payload = load_yaml(approved_lockfile)
    assert pending_payload.get("baseline_snapshot_dir")
    assert approved_payload.get("baseline_snapshot_dir") == pending_payload.get(
        "baseline_snapshot_dir"
    )


def test_approve_seeds_toolpack_trust_store(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    pending_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
    approved_lockfile = toolpack_file.parent / "lockfile" / "toolwright.lock.yaml"
    root_path = tmp_path / "root"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(root_path),
            "gate",
            "allow",
            "--all",
            "--lockfile",
            str(pending_lockfile),
        ],
    )

    assert result.exit_code == 0
    assert approved_lockfile.exists()

    source_trust_store = root_path / "state" / "keys" / "trusted_signers.json"
    assert source_trust_store.exists()

    seeded_root = toolpack_file.parent / ".toolwright"
    seeded_trust_store = seeded_root / "state" / "keys" / "trusted_signers.json"
    assert seeded_trust_store.exists()

    # Ensure the seeded trust store contains the key that signed the lockfile approvals.
    manager = LockfileManager(approved_lockfile)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    assert tool.approval_key_id

    seeded_payload = json.loads(seeded_trust_store.read_text(encoding="utf-8"))
    trusted = seeded_payload.get("trusted_keys", [])
    assert any(
        isinstance(item, dict) and item.get("key_id") == tool.approval_key_id for item in trusted
    )

    # Regression: runtime signature verification should succeed using the seeded root.
    engine = DecisionEngine(ConfirmationStore(str(tmp_path / "confirmations.db")))
    context = DecisionContext(
        approval_root_path=str(seeded_root),
        require_signed_approvals=True,
    )
    assert engine._verify_approval_signature(tool=tool, context=context) is None
