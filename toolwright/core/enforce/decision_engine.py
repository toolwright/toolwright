"""Shared decision engine for enforce gateway and MCP runtime."""

from __future__ import annotations

from typing import Any

from toolwright.core.approval.lockfile import ApprovalStatus
from toolwright.core.approval.signing import ApprovalSigner
from toolwright.core.enforce.confirmation_store import ConfirmationStore
from toolwright.models.decision import (
    DecisionContext,
    DecisionRequest,
    DecisionResult,
    DecisionType,
    ReasonCode,
)
from toolwright.models.policy import Policy, RuleType, StateChangingOverride
from toolwright.utils.canonical import canonical_request_digest


class DecisionEngine:
    """Evaluate runtime governance decisions for tool invocations."""

    STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, confirmation_store: ConfirmationStore | None = None) -> None:
        self.confirmation_store = confirmation_store or ConfirmationStore()

    def evaluate(self, request: DecisionRequest, context: DecisionContext) -> DecisionResult:
        """Return an allow/deny/confirm decision for a request."""
        action = self._resolve_action(request, context)
        if action is None:
            return DecisionResult(
                decision=DecisionType.DENY,
                reason_code=ReasonCode.DENIED_UNKNOWN_ACTION,
                reason_message=f"Unknown action/tool_id '{request.tool_id}'",
                audit_fields={"tool_id": request.tool_id},
            )

        method = request.method or str(action.get("method", "GET"))
        path = request.path or str(action.get("path", "/"))
        host = request.host or str(action.get("host", ""))
        risk_tier = str(action.get("risk_tier", "low"))
        signature_id = str(action.get("signature_id", ""))
        request_digest = canonical_request_digest(
            tool_id=request.tool_id,
            method=method,
            path=path,
            host=host,
            params=request.params,
        )
        audit_fields: dict[str, Any] = {
            "tool_id": request.tool_id,
            "action_name": request.action_name,
            "method": method.upper(),
            "path": path,
            "host": host,
            "request_digest": request_digest,
        }

        integrity_failure = self._check_integrity(context)
        if integrity_failure:
            expected, observed = integrity_failure
            audit_fields.update({"expected_artifacts_digest": expected, "observed_artifacts_digest": observed})
            return DecisionResult(
                decision=DecisionType.DENY,
                reason_code=ReasonCode.DENIED_INTEGRITY_MISMATCH,
                reason_message="Artifact digest mismatch between lockfile and runtime artifacts",
                audit_fields=audit_fields,
            )

        approval_failure = self._check_lockfile_approval(
            request=request,
            context=context,
            action=action,
            signature_id=signature_id,
        )
        if approval_failure is not None:
            code, message = approval_failure
            return DecisionResult(
                decision=DecisionType.DENY,
                reason_code=code,
                reason_message=message,
                audit_fields=audit_fields,
            )

        policy_engine = context.policy_engine
        policy_result = None
        if policy_engine is not None:
            policy_result = policy_engine.evaluate(
                method=method,
                path=path,
                host=host,
                risk_tier=risk_tier,
                scope=request.toolset_name,
            )
            audit_fields["rule_id"] = policy_result.rule_id
            if not policy_result.allowed:
                reason = policy_result.reason or "Denied by policy"
                return DecisionResult(
                    decision=DecisionType.DENY,
                    reason_code=ReasonCode.DENIED_POLICY,
                    reason_message=reason,
                    redaction_summary={"fields": sorted(set(policy_result.redact_fields))},
                    budget_effects={
                        "budget_exceeded": policy_result.budget_exceeded,
                        "budget_remaining": policy_result.budget_remaining,
                    },
                    audit_fields={**audit_fields, "rule_id": policy_result.rule_id},
                )

        state_changing = self._is_state_changing(
            policy=context.policy,
            tool_id=request.tool_id,
            method=method,
            path=path,
            host=host,
            params=request.params,
        )
        requires_step_up = state_changing and not self._has_allow_without_confirmation(
            policy=context.policy,
            method=method,
            path=path,
            host=host,
            risk_tier=risk_tier,
            toolset_name=request.toolset_name,
        )
        if policy_result and policy_result.requires_confirmation:
            requires_step_up = True
        if str(action.get("confirmation_required", "")).strip().lower() == "always":
            requires_step_up = True

        if requires_step_up:
            if request.mode == "execute" and request.confirmation_token_id:
                if context.artifacts_digest_current is None:
                    return DecisionResult(
                        decision=DecisionType.DENY,
                        reason_code=ReasonCode.ERROR_INTERNAL,
                        reason_message="Missing artifacts digest for confirmation validation",
                        audit_fields=audit_fields,
                    )
                consumed, reason_code = self.confirmation_store.consume_if_granted(
                    token_id=request.confirmation_token_id,
                    tool_id=request.tool_id,
                    request_digest=request_digest,
                    toolset_name=request.toolset_name,
                    artifacts_digest=context.artifacts_digest_current,
                    lockfile_digest=context.lockfile_digest_current,
                )
                if consumed:
                    return DecisionResult(
                        decision=DecisionType.ALLOW,
                        reason_code=ReasonCode.ALLOWED_CONFIRMATION_GRANTED,
                        reason_message="Out-of-band confirmation grant matched request",
                        redaction_summary=self._redaction_summary(policy_result),
                        budget_effects=self._budget_effects(policy_result),
                        audit_fields=audit_fields,
                    )
                return DecisionResult(
                    decision=DecisionType.DENY,
                    reason_code=reason_code,
                    reason_message="Confirmation token invalid for this request",
                    audit_fields=audit_fields,
                )

            confirmation_token = None
            if context.artifacts_digest_current is None:
                return DecisionResult(
                    decision=DecisionType.DENY,
                    reason_code=ReasonCode.ERROR_INTERNAL,
                    reason_message="Missing artifacts digest for confirmation challenge",
                    audit_fields=audit_fields,
                )
            confirmation_token = self.confirmation_store.create_challenge(
                tool_id=request.tool_id,
                request_digest=request_digest,
                toolset_name=request.toolset_name,
                artifacts_digest=context.artifacts_digest_current,
                lockfile_digest=context.lockfile_digest_current,
                ttl_seconds=context.confirmation_ttl_seconds,
            )
            return DecisionResult(
                decision=DecisionType.CONFIRM,
                reason_code=ReasonCode.CONFIRMATION_REQUIRED,
                reason_message="State-changing request requires out-of-band approval",
                confirmation_token_id=confirmation_token,
                redaction_summary=self._redaction_summary(policy_result),
                budget_effects=self._budget_effects(policy_result),
                audit_fields=audit_fields,
            )

        return DecisionResult(
            decision=DecisionType.ALLOW,
            reason_code=ReasonCode.ALLOWED_POLICY,
            reason_message="Allowed by policy",
            redaction_summary=self._redaction_summary(policy_result),
            budget_effects=self._budget_effects(policy_result),
            audit_fields=audit_fields,
        )

    def _resolve_action(self, request: DecisionRequest, context: DecisionContext) -> dict[str, Any] | None:
        action = context.manifest_view.get(request.tool_id)
        if action is not None:
            return action
        if request.action_name and request.action_name in context.manifest_view:
            return context.manifest_view[request.action_name]
        return None

    def _check_integrity(self, context: DecisionContext) -> tuple[str, str] | None:
        lockfile_ref = context.lockfile
        if lockfile_ref is None:
            return None
        lockfile_obj = getattr(lockfile_ref, "lockfile", lockfile_ref)
        expected = getattr(lockfile_obj, "artifacts_digest", None)
        observed = context.artifacts_digest_current
        if observed is None:
            return None
        if not expected:
            return "<missing>", observed
        if expected != observed:
            return expected, observed
        return None

    def _check_lockfile_approval(
        self,
        *,
        request: DecisionRequest,
        context: DecisionContext,
        action: dict[str, Any],
        signature_id: str,
    ) -> tuple[ReasonCode, str] | None:
        manager = context.lockfile
        if manager is None:
            return None

        lookup_ids = [request.tool_id]
        if signature_id:
            lookup_ids.insert(0, signature_id)
        if request.action_name:
            lookup_ids.append(request.action_name)
        lookup_ids.append(str(action.get("name", "")))

        tool = None
        for identifier in lookup_ids:
            if identifier:
                tool = manager.get_tool(identifier)
            if tool:
                break

        if tool is None:
            return ReasonCode.DENIED_NOT_APPROVED, "Tool is missing from lockfile approvals"

        if request.toolset_name:
            if tool.toolsets and request.toolset_name not in tool.toolsets:
                return (
                    ReasonCode.DENIED_TOOLSET_NOT_ALLOWED,
                    f"Tool is not a member of toolset '{request.toolset_name}'",
                )
            if tool.approved_toolsets and request.toolset_name not in tool.approved_toolsets:
                return (
                    ReasonCode.DENIED_TOOLSET_NOT_APPROVED,
                    f"Tool is not approved for toolset '{request.toolset_name}'",
                )
            if not tool.approved_toolsets and tool.status != ApprovalStatus.APPROVED:
                return (
                    ReasonCode.DENIED_NOT_APPROVED,
                    f"Tool approval status is '{tool.status.value}'",
                )
            return self._verify_approval_signature(tool=tool, context=context)

        if tool.status != ApprovalStatus.APPROVED:
            return ReasonCode.DENIED_NOT_APPROVED, f"Tool approval status is '{tool.status.value}'"
        return self._verify_approval_signature(tool=tool, context=context)

    def _verify_approval_signature(
        self,
        *,
        tool: Any,
        context: DecisionContext,
    ) -> tuple[ReasonCode, str] | None:
        """Validate approval signature and signer identity for approved tools."""
        if not context.require_signed_approvals and not tool.approval_signature:
            return None

        if not tool.approved_by or tool.approved_at is None:
            return (
                ReasonCode.DENIED_APPROVAL_SIGNATURE_REQUIRED,
                "Approved tool is missing signer identity or approval timestamp",
            )

        if not tool.approval_signature:
            return (
                ReasonCode.DENIED_APPROVAL_SIGNATURE_REQUIRED,
                "Approved tool is missing approval signature",
            )

        if tool.approval_alg and tool.approval_alg.lower() != "ed25519":
            return (
                ReasonCode.DENIED_APPROVAL_SIGNATURE_INVALID,
                f"Unsupported approval signature algorithm '{tool.approval_alg}'",
            )

        if context.require_signed_approvals and not tool.approval_key_id:
            return (
                ReasonCode.DENIED_APPROVAL_SIGNATURE_REQUIRED,
                "Approved tool is missing approval key id",
            )

        try:
            signer = ApprovalSigner(
                root_path=context.approval_root_path or ".toolwright",
                read_only=True,
            )
        except Exception:
            return (
                ReasonCode.DENIED_APPROVAL_SIGNATURE_INVALID,
                "Unable to initialize approval signer trust store",
            )

        valid = signer.verify_approval(
            tool=tool,
            approved_by=str(tool.approved_by),
            approved_at=tool.approved_at,
            reason=tool.approval_reason,
            mode=tool.approval_mode,
            signature=str(tool.approval_signature),
        )
        if not valid:
            return (
                ReasonCode.DENIED_APPROVAL_SIGNATURE_INVALID,
                "Approval signature verification failed",
            )

        if tool.approval_key_id and tool.approval_signature:
            parts = str(tool.approval_signature).split(":")
            if len(parts) >= 2 and parts[1] != tool.approval_key_id:
                return (
                    ReasonCode.DENIED_APPROVAL_SIGNATURE_INVALID,
                    "Approval signature key id does not match lockfile metadata",
                )

        return None

    def _is_state_changing(
        self,
        *,
        policy: Policy | None,
        tool_id: str,
        method: str,
        path: str,
        host: str,
        params: dict[str, Any],
    ) -> bool:
        method_upper = method.upper()
        default_state_changing = method_upper in self.STATE_CHANGING_METHODS
        if method_upper == "GET" and self._looks_stateful_get(path=path, params=params):
            default_state_changing = True
        if policy is None:
            return default_state_changing

        override = self._find_state_changing_override(
            overrides=policy.state_changing_overrides,
            tool_id=tool_id,
            method=method,
            path=path,
            host=host,
        )
        if override is not None:
            return override.state_changing
        return default_state_changing

    def _looks_stateful_get(self, *, path: str, params: dict[str, Any]) -> bool:
        """Heuristic guardrail for GET endpoints that mutate state."""
        path_lower = path.lower()
        risky_path_tokens = (
            "/cart/add",
            "/cart/remove",
            "/checkout",
            "/favorite",
            "/favourite",
            "/wishlist",
            "/subscribe",
            "/unsubscribe",
            "/delete",
            "/remove",
            "/update",
            "/toggle",
        )
        if any(token in path_lower for token in risky_path_tokens):
            return True

        risky_param_keys = {"add", "remove", "delete", "update", "toggle"}
        if risky_param_keys.intersection({str(k).lower() for k in params}):
            return True

        for key in ("action", "op", "operation", "intent"):
            value = params.get(key)
            if not isinstance(value, str):
                continue
            value_lower = value.lower()
            if any(word in value_lower for word in ("add", "remove", "delete", "update", "set", "toggle", "checkout", "purchase")):
                return True
        return False

    def _find_state_changing_override(
        self,
        *,
        overrides: list[StateChangingOverride],
        tool_id: str,
        method: str,
        path: str,
        host: str,
    ) -> StateChangingOverride | None:
        for override in overrides:
            if override.tool_id and override.tool_id != tool_id:
                continue
            if override.method and override.method.upper() != method.upper():
                continue
            if override.path and override.path != path:
                continue
            if override.host and override.host.lower() != host.lower():
                continue
            return override
        return None

    def _has_allow_without_confirmation(
        self,
        *,
        policy: Policy | None,
        method: str,
        path: str,
        host: str,
        risk_tier: str,
        toolset_name: str | None,
    ) -> bool:
        if policy is None:
            return False
        for rule in policy.get_rules_by_priority():
            if rule.type != RuleType.ALLOW:
                continue
            if not rule.settings.get("allow_without_confirmation", False):
                continue
            if rule.match.matches(method, path, host, risk_tier=risk_tier, scope=toolset_name):
                return True
        return False

    def _redaction_summary(self, policy_result: Any | None) -> dict[str, Any]:
        if not policy_result:
            return {}
        return {"fields": sorted(set(policy_result.redact_fields))}

    def _budget_effects(self, policy_result: Any | None) -> dict[str, Any]:
        if not policy_result:
            return {}
        return {
            "budget_exceeded": policy_result.budget_exceeded,
            "budget_remaining": policy_result.budget_remaining,
        }
