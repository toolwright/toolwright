"""Tests for approval signer identity/signature behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from toolwright.cli.approve import run_approve_tool
from toolwright.core.approval import LockfileManager
from toolwright.core.approval.signing import ApprovalSigner


def _manifest() -> dict[str, object]:
    return {
        "actions": [
            {
                "name": "get_users",
                "signature_id": "sig_get_users",
                "method": "GET",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "low",
            }
        ]
    }


def _toolsets() -> dict[str, object]:
    return {
        "toolsets": {
            "readonly": {"actions": ["get_users"]},
            "write": {"actions": ["get_users"]},
        }
    }


def test_approve_records_reason_and_signature(tmp_path) -> None:
    lockfile = tmp_path / "toolwright.lock.yaml"
    root_path = tmp_path / ".toolwright"
    manager = LockfileManager(lockfile)
    manager.load()
    manager.sync_from_manifest(_manifest())
    manager.save()

    run_approve_tool(
        tool_ids=("get_users",),
        lockfile_path=str(lockfile),
        all_pending=False,
        toolset=None,
        approved_by="alice@example.com",
        reason="approved for readonly pilot",
        root_path=str(root_path),
        verbose=False,
    )

    manager = LockfileManager(lockfile)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    assert tool.approved_by == "alice@example.com"
    assert tool.approval_reason == "approved for readonly pilot"
    assert tool.approval_signature is not None
    assert tool.approval_signature.startswith("ed25519:")
    assert tool.approval_alg == "ed25519"
    assert tool.approval_key_id

    signer = ApprovalSigner(root_path=root_path)
    assert signer.verify_approval(
        tool=tool,
        approved_by=tool.approved_by or "",
        approved_at=tool.approved_at,
        reason=tool.approval_reason,
        mode=tool.approval_mode,
        signature=tool.approval_signature,
    )


def test_approve_honors_allowlisted_approvers(tmp_path, monkeypatch) -> None:
    lockfile = tmp_path / "toolwright.lock.yaml"
    manager = LockfileManager(lockfile)
    manager.load()
    manager.sync_from_manifest(_manifest())
    manager.save()

    monkeypatch.setenv("TOOLWRIGHT_APPROVERS", "security@example.com")

    with pytest.raises(SystemExit) as exc:
        run_approve_tool(
            tool_ids=("get_users",),
            lockfile_path=str(lockfile),
            all_pending=False,
            toolset=None,
            approved_by="alice@example.com",
            reason="not allowlisted",
            root_path=str(tmp_path / ".toolwright"),
            verbose=False,
        )

    assert exc.value.code == 1


def test_revoked_signing_key_fails_verification(tmp_path) -> None:
    lockfile = tmp_path / "toolwright.lock.yaml"
    root_path = tmp_path / ".toolwright"
    manager = LockfileManager(lockfile)
    manager.load()
    manager.sync_from_manifest(_manifest())
    manager.save()

    run_approve_tool(
        tool_ids=("get_users",),
        lockfile_path=str(lockfile),
        all_pending=False,
        toolset=None,
        approved_by="alice@example.com",
        reason="approved for readonly pilot",
        root_path=str(root_path),
        verbose=False,
    )

    manager = LockfileManager(lockfile)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    assert tool.approval_key_id is not None
    assert tool.approval_signature is not None

    signer = ApprovalSigner(root_path=root_path)
    signer.revoke_key(tool.approval_key_id)
    assert not signer.verify_approval(
        tool=tool,
        approved_by=tool.approved_by or "",
        approved_at=tool.approved_at,
        reason=tool.approval_reason,
        mode=tool.approval_mode,
        signature=tool.approval_signature,
    )


def test_rotated_keys_overlap_for_verification(tmp_path) -> None:
    lockfile = tmp_path / "toolwright.lock.yaml"
    root_path = tmp_path / ".toolwright"
    manager = LockfileManager(lockfile)
    manager.load()
    manager.sync_from_manifest(_manifest())
    manager.save()

    run_approve_tool(
        tool_ids=("get_users",),
        lockfile_path=str(lockfile),
        all_pending=False,
        toolset=None,
        approved_by="alice@example.com",
        reason="initial approval",
        root_path=str(root_path),
        verbose=False,
    )

    manager = LockfileManager(lockfile)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    first_sig = tool.approval_signature
    first_time = tool.approved_at
    first_reason = tool.approval_reason

    signer = ApprovalSigner(root_path=root_path)
    signer.rotate_key("alice@example.com")

    run_approve_tool(
        tool_ids=("get_users",),
        lockfile_path=str(lockfile),
        all_pending=False,
        toolset=None,
        approved_by="alice@example.com",
        reason="approval after key rotation",
        root_path=str(root_path),
        verbose=False,
    )

    manager = LockfileManager(lockfile)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    assert first_sig is not None
    assert first_time is not None
    assert signer.verify_approval(
        tool=tool,
        approved_by="alice@example.com",
        approved_at=first_time,
        reason=first_reason,
        mode=tool.approval_mode,
        signature=first_sig,
    )


def test_signature_binds_toolset_approvals(tmp_path) -> None:
    lockfile = tmp_path / "toolwright.lock.yaml"
    root_path = tmp_path / ".toolwright"
    manager = LockfileManager(lockfile)
    manager.load()
    manager.sync_from_manifest(_manifest(), toolsets=_toolsets())
    manager.save()

    approval_time = datetime(2020, 1, 1, tzinfo=UTC)
    assert manager.approve(
        "get_users",
        approved_by="alice@example.com",
        toolset="readonly",
        reason="approved for readonly pilot",
        approved_at=approval_time,
    )
    manager.save()

    manager = LockfileManager(lockfile)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    assert tool.approval_signature is not None

    signer = ApprovalSigner(root_path=root_path)
    assert signer.verify_approval(
        tool=tool,
        approved_by=tool.approved_by or "",
        approved_at=tool.approved_at,
        reason=tool.approval_reason,
        mode=tool.approval_mode,
        signature=tool.approval_signature,
    )

    # Tampering with approved toolsets must invalidate the signature.
    tool.approved_toolsets.append("write")
    assert not signer.verify_approval(
        tool=tool,
        approved_by=tool.approved_by or "",
        approved_at=tool.approved_at,
        reason=tool.approval_reason,
        mode=tool.approval_mode,
        signature=tool.approval_signature,
    )


def test_toolset_scoped_approval_signature_differs_from_full_approval(tmp_path) -> None:
    lockfile = tmp_path / "toolwright.lock.yaml"
    manager = LockfileManager(lockfile)
    manager.load()
    manager.sync_from_manifest(_manifest(), toolsets=_toolsets())
    manager.save()

    approval_time = datetime(2020, 1, 1, tzinfo=UTC)
    assert manager.approve(
        "get_users",
        approved_by="alice@example.com",
        toolset="readonly",
        reason="approved for readonly pilot",
        approved_at=approval_time,
    )
    manager.save()

    manager = LockfileManager(lockfile)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    scoped_sig = tool.approval_signature
    assert scoped_sig is not None

    assert manager.approve(
        "get_users",
        approved_by="alice@example.com",
        toolset=None,
        reason="approved for readonly pilot",
        approved_at=approval_time,
    )
    manager.save()

    manager = LockfileManager(lockfile)
    manager.load()
    tool = manager.get_tool("get_users")
    assert tool is not None
    full_sig = tool.approval_signature
    assert full_sig is not None
    assert full_sig != scoped_sig
