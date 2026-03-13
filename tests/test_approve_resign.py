"""Tests for approval signature re-signing / migration helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli
from toolwright.core.approval import LockfileManager
from toolwright.core.approval.signing import ApprovalSigner
from toolwright.core.enforce import ConfirmationStore, DecisionEngine
from toolwright.models.decision import DecisionContext


def test_approve_resign_rewrites_invalid_signatures(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

    manager = LockfileManager(lockfile_path)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None

    root_path = tmp_path / "root"
    signer = ApprovalSigner(root_path=root_path)
    actor = "tests"
    approval_time = datetime(2026, 2, 14, tzinfo=UTC)

    # Simulate a legacy / out-of-order signing bug:
    # sign while the tool is still pending, then mutate it to approved without re-signing.
    legacy_signature = signer.sign_approval(
        tool=tool,
        approved_by=actor,
        approved_at=approval_time,
        reason=None,
        mode=tool.approval_mode,
    )
    assert manager.approve(
        "get_users",
        approved_by=actor,
        reason=None,
        approval_signature=legacy_signature,
        approval_alg=signer.algorithm,
        approval_key_id=signer.key_id,
        approved_at=approval_time,
    )
    manager.save()

    engine = DecisionEngine(ConfirmationStore(str(tmp_path / "confirmations.db")))
    context = DecisionContext(
        approval_root_path=str(root_path),
        require_signed_approvals=True,
    )
    tool = LockfileManager(lockfile_path).load().tools[next(iter(manager.lockfile.tools.keys()))]  # type: ignore[union-attr]
    assert engine._verify_approval_signature(tool=tool, context=context) is not None

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(root_path),
            "gate",
            "reseal",
            "--lockfile",
            str(lockfile_path),
        ],
    )
    assert result.exit_code == 0

    manager = LockfileManager(lockfile_path)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    assert engine._verify_approval_signature(tool=tool, context=context) is None

