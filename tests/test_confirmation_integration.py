"""Integration tests for the confirmation lifecycle and audit log completeness.

Proves:
1. Confirmation flow works end-to-end (CONFIRM → GRANT → ALLOW → REPLAY rejected)
2. Audit JSONL contains entries for the 5 core ReasonCodes
3. Deny decision for integrity mismatch is properly logged
"""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.core.approval import LockfileManager
from toolwright.core.audit.decision_trace import DecisionTraceEmitter
from toolwright.core.enforce import ConfirmationStore, DecisionEngine, PolicyEngine
from toolwright.models.decision import DecisionContext, DecisionRequest, DecisionResult
from toolwright.models.policy import MatchCondition, Policy, PolicyRule, RuleType


def _allow_first_party_policy() -> Policy:
    """Policy that allows GET and requires confirmation for POST."""
    return Policy(
        name="test_policy",
        default_action=RuleType.DENY,
        rules=[
            PolicyRule(
                id="allow_gets",
                name="Allow GET requests",
                type=RuleType.ALLOW,
                priority=200,
                match=MatchCondition(methods=["GET"]),
            ),
            PolicyRule(
                id="allow_posts",
                name="Allow POST requests (confirmation still applies)",
                type=RuleType.ALLOW,
                priority=100,
                match=MatchCondition(methods=["POST"]),
            ),
        ],
    )


def _get_action() -> dict[str, object]:
    return {
        "name": "get_users",
        "tool_id": "sig_get_users",
        "signature_id": "sig_get_users",
        "method": "GET",
        "path": "/api/users",
        "host": "api.example.com",
        "risk_tier": "low",
    }


def _post_action() -> dict[str, object]:
    return {
        "name": "create_user",
        "tool_id": "sig_create_user",
        "signature_id": "sig_create_user",
        "method": "POST",
        "path": "/api/users",
        "host": "api.example.com",
        "risk_tier": "medium",
    }


def _emit_trace(
    emitter: DecisionTraceEmitter,
    result: DecisionResult,
) -> None:
    """Emit a decision trace entry from a DecisionResult."""
    emitter.emit(
        tool_id=result.audit_fields.get("tool_id"),
        scope_id=result.audit_fields.get("scope_id"),
        request_fingerprint=result.audit_fields.get("request_digest"),
        decision=result.decision.value,
        reason_code=result.reason_code.value,
        confirmation_issuer=(
            "out_of_band"
            if result.reason_code.value == "allowed_confirmation_granted"
            else None
        ),
    )


def _read_audit_log(path: Path) -> list[dict]:
    """Read all entries from the JSONL audit log."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def test_confirmation_lifecycle_with_audit_trail(tmp_path: Path) -> None:
    """Full confirmation lifecycle: CONFIRM → GRANT → ALLOW → REPLAY denied.
    Verifies audit log records all 3 decision types."""
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    audit_path = tmp_path / "audit.log.jsonl"
    emitter = DecisionTraceEmitter(
        output_path=audit_path,
        run_id="test_confirmation_lifecycle",
        lockfile_digest="lock_test",
        policy_digest="policy_test",
    )

    post_action = _post_action()
    policy = _allow_first_party_policy()
    context = DecisionContext(
        manifest_view={
            "sig_create_user": post_action,
            "create_user": post_action,
        },
        policy=policy,
        policy_engine=PolicyEngine(policy),
        lockfile=None,
        artifacts_digest_current="digest_abc",
        lockfile_digest_current="lock_test",
        require_signed_approvals=False,
    )

    # Step 1: POST tool → CONFIRM required
    confirm_result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
        ),
        context,
    )
    assert confirm_result.decision.value == "confirm"
    assert confirm_result.reason_code.value == "confirmation_required"
    assert confirm_result.confirmation_token_id is not None
    _emit_trace(emitter, confirm_result)

    # Step 2: Grant the token
    assert store.grant(confirm_result.confirmation_token_id)

    # Step 3: Retry with token → ALLOW
    allow_result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            confirmation_token_id=confirm_result.confirmation_token_id,
        ),
        context,
    )
    assert allow_result.decision.value == "allow"
    assert allow_result.reason_code.value == "allowed_confirmation_granted"
    _emit_trace(emitter, allow_result)

    # Step 4: Replay → DENY
    replay_result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            confirmation_token_id=confirm_result.confirmation_token_id,
        ),
        context,
    )
    assert replay_result.decision.value == "deny"
    assert replay_result.reason_code.value == "denied_confirmation_replay"
    _emit_trace(emitter, replay_result)

    # Verify audit log has all 3 entries
    entries = _read_audit_log(audit_path)
    assert len(entries) == 3
    reason_codes = [e["reason_code"] for e in entries]
    assert "confirmation_required" in reason_codes
    assert "allowed_confirmation_granted" in reason_codes
    assert "denied_confirmation_replay" in reason_codes

    # Verify confirmation_issuer is set on grant
    grant_entry = [e for e in entries if e["reason_code"] == "allowed_confirmation_granted"][0]
    assert grant_entry["confirmation_issuer"] == "out_of_band"


def test_audit_log_completeness_core_reason_codes(tmp_path: Path) -> None:
    """Verify audit JSONL contains entries for the 5 core ReasonCodes.

    Core contract:
    - DENIED_NOT_APPROVED: unapproved tool denied
    - ALLOWED_POLICY: approved tool allowed
    - CONFIRMATION_REQUIRED: state-changing tool triggers confirm
    - ALLOWED_CONFIRMATION_GRANTED: confirmed tool allowed
    - DENIED_INTEGRITY_MISMATCH: tampered artifacts denied
    """
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    audit_path = tmp_path / "audit.log.jsonl"
    emitter = DecisionTraceEmitter(
        output_path=audit_path,
        run_id="test_audit_completeness",
        lockfile_digest="lock_digest",
        policy_digest="policy_digest",
    )

    get_action = _get_action()
    post_action = _post_action()
    policy = _allow_first_party_policy()

    # --- 1. DENIED_NOT_APPROVED: tool in pending lockfile ---
    pending_manager = LockfileManager(tmp_path / "pending.lock.yaml")
    pending_manager.load()
    pending_manager.sync_from_manifest({"actions": [get_action]})
    # Set digest so integrity check passes, but don't approve
    assert pending_manager.lockfile is not None
    pending_manager.lockfile.artifacts_digest = "digest_current"
    pending_manager.save()

    ctx_pending = DecisionContext(
        manifest_view={"sig_get_users": get_action, "get_users": get_action},
        policy=policy,
        policy_engine=PolicyEngine(policy),
        lockfile=pending_manager,
        artifacts_digest_current="digest_current",
        require_signed_approvals=False,
    )
    r1 = engine.evaluate(
        DecisionRequest(
            tool_id="sig_get_users",
            action_name="get_users",
            method="GET",
            path="/api/users",
            host="api.example.com",
            mode="execute",
        ),
        ctx_pending,
    )
    assert r1.reason_code.value == "denied_not_approved"
    _emit_trace(emitter, r1)

    # --- 2. ALLOWED_POLICY: approved GET tool ---
    approved_manager = LockfileManager(tmp_path / "approved.lock.yaml")
    approved_manager.load()
    approved_manager.sync_from_manifest({"actions": [get_action]})
    assert approved_manager.approve("sig_get_users", "test@example.com")
    assert approved_manager.lockfile is not None
    approved_manager.lockfile.artifacts_digest = "digest_current"
    approved_manager.save()

    ctx_approved = DecisionContext(
        manifest_view={"sig_get_users": get_action, "get_users": get_action},
        policy=policy,
        policy_engine=PolicyEngine(policy),
        lockfile=approved_manager,
        artifacts_digest_current="digest_current",
        approval_root_path=str(tmp_path / ".toolwright"),
        require_signed_approvals=False,
    )
    r2 = engine.evaluate(
        DecisionRequest(
            tool_id="sig_get_users",
            action_name="get_users",
            method="GET",
            path="/api/users",
            host="api.example.com",
            mode="execute",
        ),
        ctx_approved,
    )
    assert r2.reason_code.value == "allowed_policy"
    _emit_trace(emitter, r2)

    # --- 3. CONFIRMATION_REQUIRED: POST tool ---
    ctx_post = DecisionContext(
        manifest_view={
            "sig_create_user": post_action,
            "create_user": post_action,
        },
        policy=policy,
        policy_engine=PolicyEngine(policy),
        lockfile=None,
        artifacts_digest_current="digest_current",
        lockfile_digest_current="lock_digest",
        require_signed_approvals=False,
    )
    r3 = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
        ),
        ctx_post,
    )
    assert r3.reason_code.value == "confirmation_required"
    assert r3.confirmation_token_id is not None
    _emit_trace(emitter, r3)

    # --- 4. ALLOWED_CONFIRMATION_GRANTED: grant + retry ---
    assert store.grant(r3.confirmation_token_id)
    r4 = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            confirmation_token_id=r3.confirmation_token_id,
        ),
        ctx_post,
    )
    assert r4.reason_code.value == "allowed_confirmation_granted"
    _emit_trace(emitter, r4)

    # --- 5. DENIED_INTEGRITY_MISMATCH: tampered artifacts ---
    integrity_manager = LockfileManager(tmp_path / "integrity.lock.yaml")
    integrity_manager.load()
    integrity_manager.sync_from_manifest({"actions": [get_action]})
    assert integrity_manager.approve("sig_get_users", "test@example.com")
    assert integrity_manager.lockfile is not None
    integrity_manager.lockfile.artifacts_digest = "expected_digest"
    integrity_manager.save()

    ctx_tampered = DecisionContext(
        manifest_view={"sig_get_users": get_action, "get_users": get_action},
        policy=policy,
        policy_engine=PolicyEngine(policy),
        lockfile=integrity_manager,
        artifacts_digest_current="tampered_digest",
        require_signed_approvals=False,
    )
    r5 = engine.evaluate(
        DecisionRequest(
            tool_id="sig_get_users",
            action_name="get_users",
            method="GET",
            path="/api/users",
            host="api.example.com",
            mode="execute",
        ),
        ctx_tampered,
    )
    assert r5.reason_code.value == "denied_integrity_mismatch"
    _emit_trace(emitter, r5)

    # --- Verify all 5 core ReasonCodes in audit log ---
    entries = _read_audit_log(audit_path)
    assert len(entries) == 5
    reason_codes = {e["reason_code"] for e in entries}
    expected_codes = {
        "denied_not_approved",
        "allowed_policy",
        "confirmation_required",
        "allowed_confirmation_granted",
        "denied_integrity_mismatch",
    }
    assert reason_codes == expected_codes, f"Missing: {expected_codes - reason_codes}"

    # Verify audit record schema completeness
    for entry in entries:
        assert "timestamp" in entry
        assert "run_id" in entry
        assert "decision" in entry
        assert "reason_code" in entry
        assert entry["run_id"] == "test_audit_completeness"


def test_confirmation_deny_produces_correct_decision(tmp_path: Path) -> None:
    """Denying a confirmation token should prevent the tool call."""
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)

    post_action = _post_action()
    policy = _allow_first_party_policy()
    context = DecisionContext(
        manifest_view={
            "sig_create_user": post_action,
            "create_user": post_action,
        },
        policy=policy,
        policy_engine=PolicyEngine(policy),
        lockfile=None,
        artifacts_digest_current="digest_abc",
        lockfile_digest_current="lock_test",
        require_signed_approvals=False,
    )

    # Get confirmation token
    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
        ),
        context,
    )
    assert result.confirmation_token_id is not None

    # Deny the token
    assert store.deny(result.confirmation_token_id, reason="Not authorized")

    # Retry with denied token → should fail
    retry = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            confirmation_token_id=result.confirmation_token_id,
        ),
        context,
    )
    assert retry.decision.value == "deny"
    assert retry.reason_code.value == "denied_confirmation_invalid"
