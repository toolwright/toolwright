"""Tests for approval signature verification in read-only runtime roots."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from toolwright.core.approval.lockfile import ToolApproval
from toolwright.core.approval.signing import ApprovalSigner
from toolwright.core.enforce import ConfirmationStore, DecisionEngine
from toolwright.models.decision import DecisionContext


def test_runtime_verifies_approval_signature_without_writing_keys_dir(tmp_path: Path) -> None:
    """Runtime verification should not require creating or writing keypair files."""
    signing_root = tmp_path / "signer" / ".toolwright"
    signer = ApprovalSigner(root_path=signing_root)

    approval_time = datetime(2026, 2, 14, tzinfo=UTC)
    tool = ToolApproval(
        tool_id="get_user",
        signature_id="sig_get_user",
        name="get_user",
        method="GET",
        path="/api/users/{id}",
        host="api.example.com",
    )
    tool.status = "approved"
    tool.approved_by = "tester"
    tool.approved_at = approval_time
    signature = signer.sign_approval(
        tool=tool,
        approved_by="tester",
        approved_at=approval_time,
        reason=None,
        mode=tool.approval_mode,
    )
    tool.approval_signature = signature
    tool.approval_alg = signer.algorithm
    tool.approval_key_id = signer.key_id

    readonly_root = tmp_path / "portable" / ".toolwright"
    readonly_keys = readonly_root / "state" / "keys"
    readonly_keys.mkdir(parents=True, exist_ok=True)

    # Copy trust store only; do NOT copy private/public keypair.
    readonly_trust_store = readonly_keys / "trusted_signers.json"
    readonly_trust_store.write_text(
        signer.trust_store_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # Make the keys directory read-only so a verifier cannot create keypair files.
    os.chmod(readonly_keys, 0o555)

    engine = DecisionEngine(ConfirmationStore(str(tmp_path / "confirmations.db")))
    context = DecisionContext(
        approval_root_path=str(readonly_root),
        require_signed_approvals=True,
    )

    assert engine._verify_approval_signature(tool=tool, context=context) is None
