"""Tests for enforcer and audit logging."""

import json
import time

from toolwright.core.audit import AuditLogger, EventType, FileAuditBackend, MemoryAuditBackend
from toolwright.core.enforce import ConfirmationRequest, Enforcer
from toolwright.models.policy import MatchCondition, Policy, PolicyRule, RuleType


def make_policy(rules: list[PolicyRule] | None = None) -> Policy:
    """Create a test policy."""
    return Policy(
        name="Test Policy",
        rules=rules or [],
        default_action=RuleType.DENY,
    )


class TestAuditLogger:
    """Tests for AuditLogger."""

    def test_log_event(self):
        """Test logging a basic event."""
        backend = MemoryAuditBackend()
        logger = AuditLogger(backend)

        logger.log(EventType.CAPTURE_STARTED, capture_id="cap_123")

        assert len(backend.events) == 1
        assert backend.events[0]["event_type"] == "capture_started"
        assert backend.events[0]["capture_id"] == "cap_123"
        assert "timestamp" in backend.events[0]

    def test_log_enforce_decision(self):
        """Test logging an enforcement decision."""
        backend = MemoryAuditBackend()
        logger = AuditLogger(backend)

        event = logger.log_enforce_decision(
            action_id="get_user",
            endpoint_id="abc123",
            method="GET",
            path="/api/users/1",
            host="api.example.com",
            decision="allow",
            rules_matched=["allow_get"],
            confirmation_required=False,
            budget_remaining=95,
            latency_ms=12.5,
        )

        assert event["event_type"] == "enforce_decision"
        assert event["action_id"] == "get_user"
        assert event["decision"] == "allow"
        assert event["budget_remaining"] == 95

    def test_log_confirmation_workflow(self):
        """Test logging confirmation request/grant/deny."""
        backend = MemoryAuditBackend()
        logger = AuditLogger(backend)

        # Request
        logger.log_confirmation_requested(
            action_id="delete_user",
            message="Delete this user?",
            token="token123",
        )

        # Grant
        logger.log_confirmation_granted(
            action_id="delete_user",
            token="token123",
        )

        events = backend.events
        assert len(events) == 2
        assert events[0]["event_type"] == "confirmation_requested"
        assert events[1]["event_type"] == "confirmation_granted"

    def test_get_events_by_type(self):
        """Test filtering events by type."""
        backend = MemoryAuditBackend()
        logger = AuditLogger(backend)

        logger.log(EventType.CAPTURE_STARTED)
        logger.log(EventType.ENFORCE_DECISION, decision="allow")
        logger.log(EventType.ENFORCE_DECISION, decision="deny")
        logger.log(EventType.CAPTURE_COMPLETED)

        enforce_events = backend.get_events(EventType.ENFORCE_DECISION)
        assert len(enforce_events) == 2

    def test_file_backend(self, tmp_path):
        """Test file audit backend."""
        log_file = tmp_path / "audit.jsonl"
        backend = FileAuditBackend(log_file)
        logger = AuditLogger(backend)

        logger.log(EventType.CAPTURE_STARTED, capture_id="cap_1")
        logger.log(EventType.CAPTURE_COMPLETED, capture_id="cap_1")

        # Read and verify
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

        event1 = json.loads(lines[0])
        assert event1["event_type"] == "capture_started"

        event2 = json.loads(lines[1])
        assert event2["event_type"] == "capture_completed"


class TestEnforcer:
    """Tests for Enforcer."""

    def test_allow_request(self):
        """Test allowing a request."""
        policy = make_policy([
            PolicyRule(
                id="allow_get",
                name="Allow GET",
                type=RuleType.ALLOW,
                match=MatchCondition(methods=["GET"]),
                priority=100,
            ),
        ])

        enforcer = Enforcer(policy=policy)
        result = enforcer.evaluate(method="GET", path="/api/users", host="example.com")

        assert result.allowed is True
        assert result.requires_confirmation is False

    def test_deny_request(self):
        """Test denying a request."""
        policy = make_policy([
            PolicyRule(
                id="deny_admin",
                name="Deny admin",
                type=RuleType.DENY,
                match=MatchCondition(path_pattern=r".*/admin.*"),
                priority=100,
            ),
        ])

        enforcer = Enforcer(policy=policy)
        result = enforcer.evaluate(method="GET", path="/api/admin", host="example.com")

        assert result.allowed is False
        assert "deny" in result.reason.lower() or "denied" in result.reason.lower()

    def test_default_deny(self):
        """Test default deny when no rules match."""
        policy = make_policy([])  # No rules

        enforcer = Enforcer(policy=policy)
        result = enforcer.evaluate(method="GET", path="/api/users", host="example.com")

        assert result.allowed is False
        assert "default" in result.reason.lower()

    def test_confirmation_required(self):
        """Test that confirmation is required for certain requests."""
        policy = make_policy([
            PolicyRule(
                id="confirm_delete",
                name="Confirm deletes",
                type=RuleType.CONFIRM,
                match=MatchCondition(methods=["DELETE"]),
                priority=100,
                settings={"message": "Are you sure?"},
            ),
        ])

        enforcer = Enforcer(policy=policy)
        result = enforcer.evaluate(method="DELETE", path="/api/users/1", host="example.com")

        assert result.allowed is False  # Not allowed until confirmed
        assert result.requires_confirmation is True
        assert result.confirmation_token is not None
        assert result.confirmation_message == "Are you sure?"

    def test_confirmation_workflow(self):
        """Test full confirmation workflow."""
        policy = make_policy([
            PolicyRule(
                id="confirm_delete",
                name="Confirm deletes",
                type=RuleType.CONFIRM,
                match=MatchCondition(methods=["DELETE"]),
                priority=100,
                settings={"message": "Delete?"},
            ),
        ])

        enforcer = Enforcer(policy=policy)

        # First request - needs confirmation
        result1 = enforcer.evaluate(method="DELETE", path="/api/users/1", host="example.com")
        assert result1.requires_confirmation is True
        token = result1.confirmation_token

        # Confirm
        confirmed = enforcer.confirm(token)
        assert confirmed is True

        # Second request with token - should be allowed
        result2 = enforcer.evaluate(
            method="DELETE",
            path="/api/users/1",
            host="example.com",
            confirmation_token=token,
        )
        assert result2.allowed is True

    def test_confirmation_denied(self):
        """Test denying a confirmation."""
        policy = make_policy([
            PolicyRule(
                id="confirm_delete",
                name="Confirm deletes",
                type=RuleType.CONFIRM,
                match=MatchCondition(methods=["DELETE"]),
                priority=100,
            ),
        ])

        enforcer = Enforcer(policy=policy)

        # Get confirmation token
        result = enforcer.evaluate(method="DELETE", path="/api/users/1", host="example.com")
        token = result.confirmation_token

        # Deny
        denied = enforcer.deny(token, reason="User cancelled")
        assert denied is True

        # Token should no longer be valid
        confirmed = enforcer.confirm(token)
        assert confirmed is False

    def test_confirmation_expiry(self):
        """Test that confirmations expire."""
        policy = make_policy([
            PolicyRule(
                id="confirm_delete",
                name="Confirm deletes",
                type=RuleType.CONFIRM,
                match=MatchCondition(methods=["DELETE"]),
                priority=100,
            ),
        ])

        enforcer = Enforcer(policy=policy, confirmation_timeout=0.1)  # 100ms

        # Get token
        result = enforcer.evaluate(method="DELETE", path="/api/users/1", host="example.com")
        token = result.confirmation_token

        # Wait for expiry
        time.sleep(0.15)

        # Token should be expired
        confirmed = enforcer.confirm(token)
        assert confirmed is False

    def test_budget_tracking(self):
        """Test budget tracking in enforcer."""
        policy = make_policy([
            PolicyRule(
                id="budget_writes",
                name="Budget writes",
                type=RuleType.BUDGET,
                match=MatchCondition(methods=["POST"]),
                priority=100,
                settings={"per_minute": 3},
            ),
        ])

        enforcer = Enforcer(policy=policy)

        # Use up budget
        for _ in range(3):
            result = enforcer.evaluate(method="POST", path="/api/users", host="example.com")
            assert result.allowed is True

        # Budget exceeded
        result = enforcer.evaluate(method="POST", path="/api/users", host="example.com")
        assert result.allowed is False
        assert result.budget_exceeded is True

    def test_audit_logging(self):
        """Test that enforcer logs audit events."""
        backend = MemoryAuditBackend()
        logger = AuditLogger(backend)

        policy = make_policy([
            PolicyRule(
                id="allow_get",
                name="Allow GET",
                type=RuleType.ALLOW,
                match=MatchCondition(methods=["GET"]),
                priority=100,
            ),
        ])

        enforcer = Enforcer(policy=policy, audit_logger=logger)
        enforcer.evaluate(
            method="GET",
            path="/api/users",
            host="example.com",
            action_id="get_users",
        )

        events = backend.get_events(EventType.ENFORCE_DECISION)
        assert len(events) == 1
        assert events[0]["action_id"] == "get_users"
        assert events[0]["decision"] == "allow"

    def test_audit_blocked_request(self):
        """Test that blocked requests are logged."""
        backend = MemoryAuditBackend()
        logger = AuditLogger(backend)

        policy = make_policy([
            PolicyRule(
                id="deny_admin",
                name="Deny admin",
                type=RuleType.DENY,
                match=MatchCondition(path_pattern=r".*/admin.*"),
                priority=100,
            ),
        ])

        enforcer = Enforcer(policy=policy, audit_logger=logger)
        enforcer.evaluate(method="GET", path="/api/admin", host="example.com")

        blocked_events = backend.get_events(EventType.REQUEST_BLOCKED)
        assert len(blocked_events) == 1
        assert blocked_events[0]["rule_id"] == "deny_admin"

    def test_get_pending_confirmations(self):
        """Test getting pending confirmations."""
        policy = make_policy([
            PolicyRule(
                id="confirm_delete",
                name="Confirm deletes",
                type=RuleType.CONFIRM,
                match=MatchCondition(methods=["DELETE"]),
                priority=100,
            ),
        ])

        enforcer = Enforcer(policy=policy)

        # Create some confirmations
        enforcer.evaluate(method="DELETE", path="/api/users/1", host="example.com")
        enforcer.evaluate(method="DELETE", path="/api/users/2", host="example.com")

        pending = enforcer.get_pending_confirmations()
        assert len(pending) == 2

    def test_confirmation_callback(self):
        """Test confirmation callback is called."""
        policy = make_policy([
            PolicyRule(
                id="confirm_delete",
                name="Confirm deletes",
                type=RuleType.CONFIRM,
                match=MatchCondition(methods=["DELETE"]),
                priority=100,
                settings={"message": "Confirm?"},
            ),
        ])

        callback_requests = []

        def on_confirmation(req: ConfirmationRequest):
            callback_requests.append(req)

        enforcer = Enforcer(policy=policy, on_confirmation_request=on_confirmation)
        enforcer.evaluate(method="DELETE", path="/api/users/1", host="example.com")

        assert len(callback_requests) == 1
        assert callback_requests[0].message == "Confirm?"

    def test_from_yaml(self):
        """Test creating enforcer from YAML."""
        yaml_content = """
name: Test Policy
default_action: deny
rules:
  - id: allow_get
    name: Allow GET
    type: allow
    priority: 100
    match:
      methods:
        - GET
"""
        enforcer = Enforcer.from_yaml(yaml_content)

        result = enforcer.evaluate(method="GET", path="/api", host="example.com")
        assert result.allowed is True

        result = enforcer.evaluate(method="POST", path="/api", host="example.com")
        assert result.allowed is False

    def test_redaction_fields_passed_through(self):
        """Test that redaction fields are passed through."""
        policy = Policy(
            name="Test",
            redact_headers=["authorization", "x-secret"],
            rules=[
                PolicyRule(
                    id="allow_all",
                    name="Allow all",
                    type=RuleType.ALLOW,
                    match=MatchCondition(),
                    priority=100,
                ),
            ],
        )

        enforcer = Enforcer(policy=policy)
        result = enforcer.evaluate(method="GET", path="/api", host="example.com")

        assert result.redact_fields is not None
        assert "authorization" in result.redact_fields
        assert "x-secret" in result.redact_fields
