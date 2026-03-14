"""Tests for Ed25519 signature verification in gate check flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from toolwright.core.approval import ApprovalStatus, LockfileManager, ToolApproval
from toolwright.core.approval.signing import ApprovalSigner
from toolwright.core.approval.snapshot import materialize_snapshot
from tests.helpers import write_demo_toolpack


@pytest.fixture
def tmp_lockfile(tmp_path: Path) -> Path:
    return tmp_path / "toolwright.lock.yaml"


@pytest.fixture
def signer(tmp_path: Path) -> ApprovalSigner:
    root = tmp_path / ".toolwright"
    return ApprovalSigner(root_path=root)


@pytest.fixture
def sample_manifest() -> dict:
    return {
        "actions": [
            {
                "name": "get_users",
                "signature_id": "sig_get_users",
                "method": "GET",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "low",
            },
            {
                "name": "create_user",
                "signature_id": "sig_create_user",
                "method": "POST",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "medium",
            },
        ]
    }


def _setup_approved_lockfile(
    tmp_path: Path,
    sample_manifest: dict,
) -> tuple[LockfileManager, ApprovalSigner]:
    """Helper: sync manifest, approve all tools with valid signatures."""
    lockfile_path = tmp_path / "toolwright.lock.yaml"
    root = tmp_path / ".toolwright"
    signer = ApprovalSigner(root_path=root)
    manager = LockfileManager(lockfile_path)
    manager.load()
    manager.sync_from_manifest(sample_manifest)

    for tool_id, tool in manager.lockfile.tools.items():
        approval_time = datetime.now(UTC)
        actor = "admin"
        manager.approve(
            tool_id,
            actor,
            approval_signature="pending",
            approval_alg=signer.algorithm,
            approval_key_id=signer.key_id,
            approved_at=approval_time,
        )
        sig = signer.sign_approval(
            tool=tool,
            approved_by=actor,
            approved_at=approval_time,
            reason=None,
            mode=tool.approval_mode,
        )
        tool.approval_signature = sig
        tool.approval_alg = signer.algorithm
        tool.approval_key_id = signer.key_id

    manager.save()
    return manager, signer


class TestSignatureVerification:
    """Tests that check_approvals verifies Ed25519 signatures."""

    def test_valid_signatures_pass(
        self, tmp_path: Path, sample_manifest: dict
    ) -> None:
        """check_approvals should pass when all signatures are valid."""
        manager, _signer = _setup_approved_lockfile(tmp_path, sample_manifest)
        passed, message = manager.check_approvals()
        assert passed is True
        assert "All tools approved" in message

    def test_tampered_signature_detected(
        self, tmp_path: Path, sample_manifest: dict
    ) -> None:
        """check_approvals should fail when a signature is tampered with."""
        manager, _signer = _setup_approved_lockfile(tmp_path, sample_manifest)

        # Tamper with a signature
        tool = list(manager.lockfile.tools.values())[0]
        tool.approval_signature = "ed25519:fakekeyid:AAAA_tampered_sig"

        passed, message = manager.check_approvals()
        assert passed is False
        assert tool.name in message

    def test_missing_signature_detected(
        self, tmp_path: Path, sample_manifest: dict
    ) -> None:
        """check_approvals should fail when a signature is missing."""
        manager, _signer = _setup_approved_lockfile(tmp_path, sample_manifest)

        # Remove signature
        tool = list(manager.lockfile.tools.values())[0]
        tool.approval_signature = None

        passed, message = manager.check_approvals()
        assert passed is False
        assert tool.name in message

    def test_tampered_risk_tier_detected(
        self, tmp_path: Path, sample_manifest: dict
    ) -> None:
        """Changing risk_tier after signing should invalidate the signature."""
        manager, _signer = _setup_approved_lockfile(tmp_path, sample_manifest)

        # Tamper with risk_tier (signature was computed with original value)
        tool = list(manager.lockfile.tools.values())[0]
        tool.risk_tier = "critical"

        passed, message = manager.check_approvals()
        assert passed is False
        assert tool.name in message

    def test_tampered_artifacts_digest_detected(self, tmp_path: Path) -> None:
        """check_ci should fail when artifacts_digest is tampered with."""
        toolpack_file = write_demo_toolpack(tmp_path)
        lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
        manager = LockfileManager(lockfile_path)
        manager.load()
        manager.approve_all()
        result = materialize_snapshot(lockfile_path)
        relative_dir = result.snapshot_dir.relative_to(toolpack_file.parent)
        manager.set_baseline_snapshot(str(relative_dir), result.digest)

        # Tamper with the artifacts_digest
        assert manager.lockfile is not None
        manager.lockfile.artifacts_digest = "sha256:tampered_digest_value"
        manager.save()

        passed, message = manager.check_ci()
        assert passed is False
        assert "tampered" in message.lower() or "mismatch" in message.lower()
