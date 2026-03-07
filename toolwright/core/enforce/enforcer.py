"""Runtime enforcement gateway."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from toolwright.core.audit import AuditLogger, MemoryAuditBackend
from toolwright.core.enforce.engine import PolicyEngine
from toolwright.models.policy import Policy


@dataclass
class ConfirmationRequest:
    """A pending confirmation request."""

    token: str
    action_id: str | None
    method: str
    path: str
    host: str
    message: str
    created_at: float
    expires_at: float


@dataclass
class EnforceResult:
    """Result of enforcement evaluation."""

    allowed: bool
    requires_confirmation: bool = False
    confirmation_token: str | None = None
    confirmation_message: str | None = None
    budget_exceeded: bool = False
    budget_remaining: int | None = None
    reason: str = ""
    rule_id: str | None = None

    # Audit/redaction info
    redact_fields: list[str] | None = None
    audit_level: str = "standard"


class Enforcer:
    """Runtime enforcement gateway for tool calls."""

    def __init__(
        self,
        policy: Policy | None = None,
        policy_engine: PolicyEngine | None = None,
        audit_logger: AuditLogger | None = None,
        confirmation_timeout: int = 300,  # 5 minutes
        on_confirmation_request: Callable[[ConfirmationRequest], None] | None = None,
    ) -> None:
        """Initialize the enforcer.

        Args:
            policy: Policy to enforce (creates PolicyEngine)
            policy_engine: Existing PolicyEngine to use
            audit_logger: Logger for audit events
            confirmation_timeout: Timeout for confirmations in seconds
            on_confirmation_request: Callback when confirmation is needed
        """
        if policy_engine:
            self.engine = policy_engine
        elif policy:
            self.engine = PolicyEngine(policy)
        else:
            raise ValueError("Must provide policy or policy_engine")

        self.audit_logger = audit_logger or AuditLogger(MemoryAuditBackend())
        self.confirmation_timeout = confirmation_timeout
        self.on_confirmation_request = on_confirmation_request

        # Pending confirmations
        self._pending_confirmations: dict[str, ConfirmationRequest] = {}

        # Granted confirmations (token -> expiry time)
        self._granted_confirmations: dict[str, float] = {}

    @property
    def policy(self) -> Policy:
        """Get the current policy."""
        return self.engine.policy

    def evaluate(
        self,
        method: str,
        path: str,
        host: str,
        action_id: str | None = None,
        endpoint_id: str | None = None,
        headers: dict[str, str] | None = None,
        risk_tier: str | None = None,
        scope: str | None = None,
        confirmation_token: str | None = None,
        caller_context: dict[str, Any] | None = None,
    ) -> EnforceResult:
        """Evaluate a request against the policy.

        Args:
            method: HTTP method
            path: Request path
            host: Request host
            action_id: ID of the action/tool
            endpoint_id: ID of the endpoint
            headers: Request headers
            risk_tier: Risk tier of the endpoint
            scope: Scope name
            confirmation_token: Token from previous confirmation request
            caller_context: Additional context about the caller

        Returns:
            EnforceResult with decision and details
        """
        start_time = time.time()

        # Check if we have a valid confirmation token.
        # NOTE: This short-circuits before engine.evaluate(), so budget is
        # consumed only once (during the initial evaluate() call below).
        # If this flow is refactored, use the dry_run/consume_budget pattern
        # from DecisionEngine to prevent double-counting.
        if confirmation_token and self._check_confirmation_token(confirmation_token):
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_enforce_decision(
                action_id=action_id,
                endpoint_id=endpoint_id,
                method=method,
                path=path,
                host=host,
                decision="allow",
                rules_matched=["confirmation_granted"],
                confirmation_required=False,
                latency_ms=latency_ms,
                caller_context=caller_context,
            )
            return EnforceResult(
                allowed=True,
                reason="Confirmation token valid",
            )

        # Evaluate against policy
        result = self.engine.evaluate(
            method=method,
            path=path,
            host=host,
            headers=headers,
            risk_tier=risk_tier,
            scope=scope,
        )

        latency_ms = (time.time() - start_time) * 1000

        # Handle budget exceeded
        if result.budget_exceeded:
            self.audit_logger.log_budget_exceeded(
                action_id=action_id,
                rule_id=result.rule_id or "unknown",
                limit_type="per_minute",
            )
            self.audit_logger.log_request_blocked(
                action_id=action_id,
                method=method,
                path=path,
                host=host,
                reason="Budget exceeded",
                rule_id=result.rule_id,
            )
            return EnforceResult(
                allowed=False,
                budget_exceeded=True,
                budget_remaining=0,
                reason="Budget exceeded",
                rule_id=result.rule_id,
                redact_fields=result.redact_fields,
                audit_level=result.audit_level,
            )

        # Handle deny
        if not result.allowed:
            self.audit_logger.log_request_blocked(
                action_id=action_id,
                method=method,
                path=path,
                host=host,
                reason=result.reason,
                rule_id=result.rule_id,
            )
            return EnforceResult(
                allowed=False,
                reason=result.reason,
                rule_id=result.rule_id,
                redact_fields=result.redact_fields,
                audit_level=result.audit_level,
            )

        # Handle confirmation required
        if result.requires_confirmation:
            token = self._create_confirmation_request(
                action_id=action_id,
                method=method,
                path=path,
                host=host,
                message=result.confirmation_message or "Confirmation required",
            )
            self.audit_logger.log_enforce_decision(
                action_id=action_id,
                endpoint_id=endpoint_id,
                method=method,
                path=path,
                host=host,
                decision="pending_confirmation",
                rules_matched=[result.rule_id] if result.rule_id else [],
                confirmation_required=True,
                budget_remaining=result.budget_remaining,
                latency_ms=latency_ms,
                caller_context=caller_context,
            )
            return EnforceResult(
                allowed=False,  # Not allowed until confirmed
                requires_confirmation=True,
                confirmation_token=token,
                confirmation_message=result.confirmation_message,
                reason="Confirmation required",
                rule_id=result.rule_id,
                redact_fields=result.redact_fields,
                audit_level=result.audit_level,
            )

        # Allowed
        self.audit_logger.log_enforce_decision(
            action_id=action_id,
            endpoint_id=endpoint_id,
            method=method,
            path=path,
            host=host,
            decision="allow",
            rules_matched=[result.rule_id] if result.rule_id else [],
            confirmation_required=False,
            budget_remaining=result.budget_remaining,
            latency_ms=latency_ms,
            caller_context=caller_context,
        )

        return EnforceResult(
            allowed=True,
            budget_remaining=result.budget_remaining,
            reason=result.reason,
            rule_id=result.rule_id,
            redact_fields=result.redact_fields,
            audit_level=result.audit_level,
        )

    def _create_confirmation_request(
        self,
        action_id: str | None,
        method: str,
        path: str,
        host: str,
        message: str,
    ) -> str:
        """Create a confirmation request.

        Args:
            action_id: ID of the action
            method: HTTP method
            path: Request path
            host: Request host
            message: Confirmation message

        Returns:
            Confirmation token
        """
        token = secrets.token_urlsafe(32)
        now = time.time()

        request = ConfirmationRequest(
            token=token,
            action_id=action_id,
            method=method,
            path=path,
            host=host,
            message=message,
            created_at=now,
            expires_at=now + self.confirmation_timeout,
        )

        self._pending_confirmations[token] = request

        self.audit_logger.log_confirmation_requested(
            action_id=action_id,
            message=message,
            token=token,
        )

        # Call callback if provided
        if self.on_confirmation_request:
            self.on_confirmation_request(request)

        return token

    def confirm(self, token: str) -> bool:
        """Confirm a pending request.

        Args:
            token: Confirmation token

        Returns:
            True if confirmation was successful
        """
        request = self._pending_confirmations.pop(token, None)

        if request is None:
            return False

        # Check if expired
        if time.time() > request.expires_at:
            self.audit_logger.log_confirmation_denied(
                action_id=request.action_id,
                token=token,
                reason="Token expired",
            )
            return False

        # Grant confirmation
        self._granted_confirmations[token] = request.expires_at

        self.audit_logger.log_confirmation_granted(
            action_id=request.action_id,
            token=token,
        )

        return True

    def deny(self, token: str, reason: str | None = None) -> bool:
        """Deny a pending confirmation request.

        Args:
            token: Confirmation token
            reason: Reason for denial

        Returns:
            True if denial was processed
        """
        request = self._pending_confirmations.pop(token, None)

        if request is None:
            return False

        self.audit_logger.log_confirmation_denied(
            action_id=request.action_id,
            token=token,
            reason=reason,
        )

        return True

    def _check_confirmation_token(self, token: str) -> bool:
        """Check if a confirmation token is valid.

        Args:
            token: Token to check

        Returns:
            True if valid and not expired
        """
        expires_at = self._granted_confirmations.get(token)

        if expires_at is None:
            return False

        if time.time() > expires_at:
            # Expired, remove it
            del self._granted_confirmations[token]
            return False

        return True

    def get_pending_confirmations(self) -> list[ConfirmationRequest]:
        """Get all pending confirmation requests.

        Returns:
            List of pending requests
        """
        # Clean up expired requests
        now = time.time()
        expired = [t for t, r in self._pending_confirmations.items() if now > r.expires_at]
        for token in expired:
            del self._pending_confirmations[token]

        return list(self._pending_confirmations.values())

    def reset_budget(self, rule_id: str) -> None:
        """Reset budget for a rule.

        Args:
            rule_id: ID of the budget rule
        """
        self.engine.reset_budget(rule_id)

    def reset_all_budgets(self) -> None:
        """Reset all budgets."""
        self.engine.reset_all_budgets()

    @classmethod
    def from_yaml(
        cls,
        yaml_content: str,
        audit_logger: AuditLogger | None = None,
        **kwargs: Any,
    ) -> Enforcer:
        """Create an Enforcer from YAML policy.

        Args:
            yaml_content: YAML policy content
            audit_logger: Optional audit logger
            **kwargs: Additional arguments for Enforcer

        Returns:
            Enforcer instance
        """
        engine = PolicyEngine.from_yaml(yaml_content)
        return cls(policy_engine=engine, audit_logger=audit_logger, **kwargs)

    @classmethod
    def from_file(
        cls,
        file_path: str,
        audit_logger: AuditLogger | None = None,
        **kwargs: Any,
    ) -> Enforcer:
        """Create an Enforcer from YAML policy file.

        Args:
            file_path: Path to policy file
            audit_logger: Optional audit logger
            **kwargs: Additional arguments for Enforcer

        Returns:
            Enforcer instance
        """
        engine = PolicyEngine.from_file(file_path)
        return cls(policy_engine=engine, audit_logger=audit_logger, **kwargs)
