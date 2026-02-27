"""Tests for shared DecisionEngine governance behavior."""

from __future__ import annotations

from pathlib import Path

import toolwright.core.enforce.confirmation_store as confirmation_store_module
from toolwright.core.approval import LockfileManager
from toolwright.core.enforce import ConfirmationStore, DecisionEngine, PolicyEngine
from toolwright.models.decision import DecisionContext, DecisionRequest
from toolwright.models.policy import (
    MatchCondition,
    Policy,
    PolicyRule,
    RuleType,
    StateChangingOverride,
)


def _allow_all_policy() -> Policy:
    return Policy(
        name="allow_all",
        default_action=RuleType.DENY,
        rules=[
            PolicyRule(
                id="allow_all",
                name="Allow all",
                type=RuleType.ALLOW,
                priority=100,
                match=MatchCondition(),
            )
        ],
    )


def _manifest_action(method: str = "POST") -> dict[str, object]:
    return {
        "name": "create_user",
        "tool_id": "sig_create_user",
        "signature_id": "sig_create_user",
        "method": method,
        "path": "/api/users",
        "host": "api.example.com",
        "risk_tier": "medium",
    }


def _context(
    *,
    action: dict[str, object],
    policy: Policy,
    lockfile_manager: LockfileManager | None = None,
    artifacts_digest: str = "digest_current",
    lockfile_digest: str | None = None,
    approval_root: str | None = None,
    require_signed: bool = True,
) -> DecisionContext:
    policy_engine = PolicyEngine(policy)
    return DecisionContext(
        manifest_view={
            "sig_create_user": action,
            "create_user": action,
        },
        policy=policy,
        policy_engine=policy_engine,
        lockfile=lockfile_manager,
        artifacts_digest_current=artifacts_digest,
        lockfile_digest_current=lockfile_digest,
        approval_root_path=approval_root,
        require_signed_approvals=require_signed,
    )


def test_write_requires_confirmation_and_grant_is_single_use(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("POST")
    context = _context(action=action, policy=_allow_all_policy())

    first = engine.evaluate(
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
    assert first.decision.value == "confirm"
    assert first.confirmation_token_id is not None

    assert store.grant(first.confirmation_token_id)

    second = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            confirmation_token_id=first.confirmation_token_id,
        ),
        context,
    )
    assert second.decision.value == "allow"
    assert second.reason_code.value == "allowed_confirmation_granted"

    replay = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            confirmation_token_id=first.confirmation_token_id,
        ),
        context,
    )
    assert replay.decision.value == "deny"
    assert replay.reason_code.value == "denied_confirmation_replay"


def test_allow_without_confirmation_skips_step_up_for_scoped_allow(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)

    action = {
        "name": "query_recently_viewed_products",
        "tool_id": "sig_graphql_query",
        "signature_id": "sig_graphql_query",
        "method": "POST",
        "path": "/api/graphql",
        "host": "stockx.com",
        "risk_tier": "medium",
    }

    policy = Policy(
        name="graphql_readonly_policy",
        default_action=RuleType.DENY,
        rules=[
            PolicyRule(
                id="allow_graphql_readonly",
                name="Allow GraphQL query operations in readonly toolset",
                type=RuleType.ALLOW,
                priority=200,
                match=MatchCondition(
                    methods=["POST"],
                    hosts=["stockx.com"],
                    path_pattern=r".*/graphql.*",
                    scopes=["readonly"],
                ),
                settings={"allow_without_confirmation": True},
            ),
            PolicyRule(
                id="confirm_posts",
                name="Confirm POST by default",
                type=RuleType.CONFIRM,
                priority=100,
                match=MatchCondition(methods=["POST"]),
                settings={"message": "Confirm"},
            ),
        ],
    )

    context = DecisionContext(
        manifest_view={
            "sig_graphql_query": action,
            "query_recently_viewed_products": action,
        },
        policy=policy,
        policy_engine=PolicyEngine(policy),
        lockfile=None,
        artifacts_digest_current="digest_current",
        lockfile_digest_current=None,
        approval_root_path=None,
        require_signed_approvals=False,
    )

    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_graphql_query",
            action_name="query_recently_viewed_products",
            method="POST",
            path="/api/graphql",
            host="stockx.com",
            params={"variables": {}},
            toolset_name="readonly",
            mode="execute",
        ),
        context,
    )

    assert result.decision.value == "allow"


def test_confirmation_required_always_enforced_for_read_requests(tmp_path: Path) -> None:
    """High/critical-risk reads should still require explicit confirmation when configured."""
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)

    action = {
        "name": "get_mfa",
        "tool_id": "sig_get_mfa",
        "signature_id": "sig_get_mfa",
        "method": "GET",
        "path": "/api/mfa",
        "host": "api.example.com",
        "risk_tier": "critical",
        "confirmation_required": "always",
    }

    policy = _allow_all_policy()
    context = DecisionContext(
        manifest_view={
            "sig_get_mfa": action,
            "get_mfa": action,
        },
        policy=policy,
        policy_engine=PolicyEngine(policy),
        lockfile=None,
        artifacts_digest_current="digest_current",
        lockfile_digest_current=None,
        approval_root_path=None,
        require_signed_approvals=False,
    )

    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_get_mfa",
            action_name="get_mfa",
            method="GET",
            path="/api/mfa",
            host="api.example.com",
            params={},
            mode="execute",
        ),
        context,
    )

    assert result.decision.value == "confirm"


def test_confirmation_token_rejects_request_digest_mismatch(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("POST")
    context = _context(action=action, policy=_allow_all_policy())

    initial = engine.evaluate(
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
    assert initial.confirmation_token_id is not None
    assert store.grant(initial.confirmation_token_id)

    mismatch = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "John"},
            mode="execute",
            confirmation_token_id=initial.confirmation_token_id,
        ),
        context,
    )
    assert mismatch.decision.value == "deny"
    assert mismatch.reason_code.value == "denied_confirmation_invalid"


def test_confirmation_token_rejects_toolset_mismatch(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("POST")
    context = _context(action=action, policy=_allow_all_policy())

    initial = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            toolset_name="readonly",
        ),
        context,
    )
    assert initial.confirmation_token_id is not None
    assert store.grant(initial.confirmation_token_id)

    mismatch = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            toolset_name="writer",
            confirmation_token_id=initial.confirmation_token_id,
        ),
        context,
    )
    assert mismatch.decision.value == "deny"
    assert mismatch.reason_code.value == "denied_confirmation_invalid"


def test_confirmation_token_rejects_artifacts_digest_mismatch(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("POST")
    base_policy = _allow_all_policy()

    context_issue = _context(
        action=action,
        policy=base_policy,
        artifacts_digest="digest_issue",
        lockfile_digest="lock_digest",
    )
    issued = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
        ),
        context_issue,
    )
    assert issued.confirmation_token_id is not None
    assert store.grant(issued.confirmation_token_id)

    context_execute = _context(
        action=action,
        policy=base_policy,
        artifacts_digest="digest_other",
        lockfile_digest="lock_digest",
    )
    mismatch = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            confirmation_token_id=issued.confirmation_token_id,
        ),
        context_execute,
    )
    assert mismatch.decision.value == "deny"
    assert mismatch.reason_code.value == "denied_confirmation_invalid"


def test_confirmation_token_rejects_expired_challenge(tmp_path: Path, monkeypatch) -> None:
    now = [1_700_000_000.0]
    monkeypatch.setattr(confirmation_store_module.time, "time", lambda: now[0])

    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("POST")
    context = _context(action=action, policy=_allow_all_policy())
    context.confirmation_ttl_seconds = 1

    issued = engine.evaluate(
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
    assert issued.confirmation_token_id is not None
    assert store.grant(issued.confirmation_token_id)

    now[0] += 2
    expired = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            params={"name": "Jane"},
            mode="execute",
            confirmation_token_id=issued.confirmation_token_id,
        ),
        context,
    )
    assert expired.decision.value == "deny"
    assert expired.reason_code.value == "denied_confirmation_expired"


def test_integrity_mismatch_denies_before_policy(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("GET")
    policy = _allow_all_policy()

    lockfile_manager = LockfileManager(tmp_path / "toolwright.lock.yaml")
    lockfile = lockfile_manager.load()
    lockfile.artifacts_digest = "expected_digest"

    context = _context(
        action=action,
        policy=policy,
        lockfile_manager=lockfile_manager,
        artifacts_digest="observed_digest",
    )

    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="GET",
            path="/api/users",
            host="api.example.com",
            mode="execute",
        ),
        context,
    )
    assert result.decision.value == "deny"
    assert result.reason_code.value == "denied_integrity_mismatch"


def test_state_changing_override_can_disable_step_up(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("POST")
    policy = _allow_all_policy()
    policy.state_changing_overrides = [
        StateChangingOverride(tool_id="sig_create_user", state_changing=False)
    ]
    context = _context(action=action, policy=policy)

    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/api/users",
            host="api.example.com",
            mode="execute",
        ),
        context,
    )
    assert result.decision.value == "allow"
    assert result.reason_code.value == "allowed_policy"


def test_graphql_mutation_is_treated_as_state_changing(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("POST")
    action["path"] = "/graphql"
    policy = _allow_all_policy()
    context = _context(action=action, policy=policy)

    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="POST",
            path="/graphql",
            host="api.example.com",
            params={"query": "mutation { createUser(name: \\\"A\\\") { id } }"},
            mode="execute",
        ),
        context,
    )
    assert result.decision.value == "confirm"
    assert result.reason_code.value == "confirmation_required"


def test_stateful_get_path_is_treated_as_write_candidate(tmp_path: Path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("GET")
    action["path"] = "/cart/add"
    policy = _allow_all_policy()
    context = _context(action=action, policy=policy)

    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="GET",
            path="/cart/add",
            host="api.example.com",
            params={"sku": "sku_123"},
            mode="execute",
        ),
        context,
    )
    assert result.decision.value == "confirm"
    assert result.reason_code.value == "confirmation_required"


def test_signed_approval_allows_runtime_when_valid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TOOLWRIGHT_ROOT", str(tmp_path / ".toolwright"))
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("GET")
    policy = _allow_all_policy()

    manager = LockfileManager(tmp_path / "toolwright.lock.yaml")
    manager.load()
    manager.sync_from_manifest({"actions": [action]})
    assert manager.approve("sig_create_user", "security@example.com")
    assert manager.lockfile is not None
    manager.lockfile.artifacts_digest = "digest_current"
    manager.save()

    context = _context(
        action=action,
        policy=policy,
        lockfile_manager=manager,
        approval_root=str(tmp_path / ".toolwright"),
    )
    context.lockfile_digest_current = "lock_digest"

    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="GET",
            path="/api/users",
            host="api.example.com",
            mode="execute",
        ),
        context,
    )
    assert result.decision.value == "allow"
    assert result.reason_code.value == "allowed_policy"


def test_missing_approval_signature_denies_when_required(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TOOLWRIGHT_ROOT", str(tmp_path / ".toolwright"))
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("GET")
    policy = _allow_all_policy()

    manager = LockfileManager(tmp_path / "toolwright.lock.yaml")
    manager.load()
    manager.sync_from_manifest({"actions": [action]})
    assert manager.approve("sig_create_user", "security@example.com")
    assert manager.lockfile is not None
    manager.lockfile.artifacts_digest = "digest_current"
    tool = manager.get_tool("sig_create_user")
    assert tool is not None
    tool.approval_signature = None
    tool.approval_key_id = None
    manager.save()

    context = _context(
        action=action,
        policy=policy,
        lockfile_manager=manager,
        approval_root=str(tmp_path / ".toolwright"),
    )
    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="GET",
            path="/api/users",
            host="api.example.com",
            mode="execute",
        ),
        context,
    )
    assert result.decision.value == "deny"
    assert result.reason_code.value == "denied_approval_signature_required"


def test_invalid_approval_signature_denies(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TOOLWRIGHT_ROOT", str(tmp_path / ".toolwright"))
    store = ConfirmationStore(tmp_path / "confirmations.db")
    engine = DecisionEngine(store)
    action = _manifest_action("GET")
    policy = _allow_all_policy()

    manager = LockfileManager(tmp_path / "toolwright.lock.yaml")
    manager.load()
    manager.sync_from_manifest({"actions": [action]})
    assert manager.approve("sig_create_user", "security@example.com")
    assert manager.lockfile is not None
    manager.lockfile.artifacts_digest = "digest_current"
    tool = manager.get_tool("sig_create_user")
    assert tool is not None
    assert tool.approval_signature is not None
    tool.approval_signature = f"{tool.approval_signature}tampered"
    manager.save()

    context = _context(
        action=action,
        policy=policy,
        lockfile_manager=manager,
        approval_root=str(tmp_path / ".toolwright"),
    )
    result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_create_user",
            action_name="create_user",
            method="GET",
            path="/api/users",
            host="api.example.com",
            mode="execute",
        ),
        context,
    )
    assert result.decision.value == "deny"
    assert result.reason_code.value == "denied_approval_signature_invalid"
