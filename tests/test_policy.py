"""Tests for policy engine."""


import pytest

from toolwright.core.enforce import PolicyEngine
from toolwright.models.policy import (
    MatchCondition,
    Policy,
    PolicyRule,
    RuleType,
)


class TestMatchCondition:
    """Tests for MatchCondition."""

    def test_match_method(self):
        """Test method matching."""
        cond = MatchCondition(methods=["GET", "POST"])
        assert cond.matches(method="GET", path="/api", host="example.com")
        assert cond.matches(method="POST", path="/api", host="example.com")
        assert not cond.matches(method="DELETE", path="/api", host="example.com")

    def test_match_hosts(self):
        """Test host matching."""
        cond = MatchCondition(hosts=["api.example.com", "api2.example.com"])
        assert cond.matches(method="GET", path="/api", host="api.example.com")
        assert cond.matches(method="GET", path="/api", host="API.EXAMPLE.COM")  # case insensitive
        assert not cond.matches(method="GET", path="/api", host="other.com")

    def test_match_host_pattern(self):
        """Test host pattern matching."""
        cond = MatchCondition(host_pattern=r".*\.example\.com")
        assert cond.matches(method="GET", path="/api", host="api.example.com")
        assert cond.matches(method="GET", path="/api", host="www.example.com")
        assert not cond.matches(method="GET", path="/api", host="example.org")

    def test_match_paths(self):
        """Test path matching."""
        cond = MatchCondition(paths=["/api/users", "/api/orders"])
        assert cond.matches(method="GET", path="/api/users", host="example.com")
        assert not cond.matches(method="GET", path="/api/products", host="example.com")

    def test_match_path_pattern(self):
        """Test path pattern matching."""
        cond = MatchCondition(path_pattern=r".*/admin.*")
        assert cond.matches(method="GET", path="/api/admin/users", host="example.com")
        assert cond.matches(method="GET", path="/admin", host="example.com")
        assert not cond.matches(method="GET", path="/api/users", host="example.com")

    def test_match_risk_tier(self):
        """Test risk tier matching."""
        cond = MatchCondition(risk_tiers=["high", "critical"])
        assert cond.matches(method="GET", path="/api", host="example.com", risk_tier="high")
        assert not cond.matches(method="GET", path="/api", host="example.com", risk_tier="low")

    def test_match_scopes(self):
        """Scope filters should only match when a scope is provided."""
        cond = MatchCondition(scopes=["readonly"])
        assert cond.matches(method="GET", path="/api", host="example.com", scope="readonly")
        assert not cond.matches(method="GET", path="/api", host="example.com", scope="operator")
        assert not cond.matches(method="GET", path="/api", host="example.com", scope=None)

    def test_match_multiple_conditions(self):
        """Test multiple conditions (AND logic)."""
        cond = MatchCondition(
            methods=["POST", "PUT"],
            hosts=["api.example.com"],
            path_pattern=r"/api/.*",
        )
        # All conditions must match
        assert cond.matches(method="POST", path="/api/users", host="api.example.com")
        # Wrong method
        assert not cond.matches(method="GET", path="/api/users", host="api.example.com")
        # Wrong host
        assert not cond.matches(method="POST", path="/api/users", host="other.com")


class TestPolicyRule:
    """Tests for PolicyRule."""

    def test_create_allow_rule(self):
        """Test creating an allow rule."""
        rule = PolicyRule(
            id="allow_get",
            name="Allow GET requests",
            type=RuleType.ALLOW,
            match=MatchCondition(methods=["GET"]),
            priority=100,
        )
        assert rule.type == RuleType.ALLOW
        assert rule.priority == 100

    def test_create_budget_rule(self):
        """Test creating a budget rule."""
        rule = PolicyRule(
            id="budget_writes",
            name="Rate limit writes",
            type=RuleType.BUDGET,
            match=MatchCondition(methods=["POST", "PUT", "PATCH"]),
            settings={"per_minute": 10, "per_hour": 100},
        )
        assert rule.type == RuleType.BUDGET
        assert rule.settings["per_minute"] == 10


class TestPolicy:
    """Tests for Policy model."""

    def test_default_policy(self):
        """Test default policy settings."""
        policy = Policy(name="Test Policy")
        assert policy.default_action == RuleType.DENY
        assert policy.audit_all is True
        assert "authorization" in policy.redact_headers

    def test_rules_by_priority(self):
        """Test getting rules sorted by priority."""
        policy = Policy(
            name="Test",
            rules=[
                PolicyRule(
                    id="low", name="Low", type=RuleType.ALLOW,
                    match=MatchCondition(), priority=10,
                ),
                PolicyRule(
                    id="high", name="High", type=RuleType.ALLOW,
                    match=MatchCondition(), priority=100,
                ),
                PolicyRule(
                    id="medium", name="Medium", type=RuleType.ALLOW,
                    match=MatchCondition(), priority=50,
                ),
            ],
        )
        sorted_rules = policy.get_rules_by_priority()
        assert sorted_rules[0].id == "high"
        assert sorted_rules[1].id == "medium"
        assert sorted_rules[2].id == "low"


class TestPolicyEngine:
    """Tests for PolicyEngine."""

    def test_evaluate_allow_rule(self):
        """Test evaluating an allow rule."""
        policy = Policy(
            name="Test",
            rules=[
                PolicyRule(
                    id="allow_get",
                    name="Allow GET",
                    type=RuleType.ALLOW,
                    match=MatchCondition(methods=["GET"]),
                    priority=100,
                ),
            ],
        )

        engine = PolicyEngine(policy)
        result = engine.evaluate(method="GET", path="/api/users", host="example.com")

        assert result.allowed is True
        assert result.rule_id == "allow_get"
        assert result.rule_type == RuleType.ALLOW

    def test_evaluate_deny_rule(self):
        """Test evaluating a deny rule."""
        policy = Policy(
            name="Test",
            rules=[
                PolicyRule(
                    id="deny_admin",
                    name="Deny admin",
                    type=RuleType.DENY,
                    match=MatchCondition(path_pattern=r".*/admin.*"),
                    priority=100,
                ),
            ],
        )

        engine = PolicyEngine(policy)
        result = engine.evaluate(method="GET", path="/api/admin/users", host="example.com")

        assert result.allowed is False
        assert result.rule_id == "deny_admin"
        assert result.rule_type == RuleType.DENY

    def test_evaluate_confirm_rule(self):
        """Test evaluating a confirm rule."""
        policy = Policy(
            name="Test",
            rules=[
                PolicyRule(
                    id="confirm_delete",
                    name="Confirm deletes",
                    type=RuleType.CONFIRM,
                    match=MatchCondition(methods=["DELETE"]),
                    priority=100,
                    settings={"message": "Are you sure?"},
                ),
            ],
        )

        engine = PolicyEngine(policy)
        result = engine.evaluate(method="DELETE", path="/api/users/1", host="example.com")

        assert result.allowed is True
        assert result.requires_confirmation is True
        assert result.confirmation_message == "Are you sure?"

    def test_evaluate_budget_rule(self):
        """Test evaluating a budget rule."""
        policy = Policy(
            name="Test",
            rules=[
                PolicyRule(
                    id="budget_writes",
                    name="Budget writes",
                    type=RuleType.BUDGET,
                    match=MatchCondition(methods=["POST"]),
                    priority=100,
                    settings={"per_minute": 5},
                ),
            ],
        )

        engine = PolicyEngine(policy)

        # Should allow requests until budget exceeded
        for i in range(5):
            result = engine.evaluate(method="POST", path="/api/users", host="example.com")
            assert result.allowed is True
            assert result.budget_remaining == 5 - i - 1

        # Budget exceeded
        result = engine.evaluate(method="POST", path="/api/users", host="example.com")
        assert result.allowed is False
        assert result.budget_exceeded is True

    def test_evaluate_default_deny(self):
        """Test default deny when no rules match."""
        policy = Policy(
            name="Test",
            default_action=RuleType.DENY,
            rules=[
                PolicyRule(
                    id="allow_get",
                    name="Allow GET only",
                    type=RuleType.ALLOW,
                    match=MatchCondition(methods=["GET"]),
                    priority=100,
                ),
            ],
        )

        engine = PolicyEngine(policy)
        result = engine.evaluate(method="POST", path="/api/users", host="example.com")

        assert result.allowed is False
        assert result.rule_id is None
        assert "default" in result.reason.lower()

    def test_evaluate_priority_order(self):
        """Test rules are evaluated in priority order."""
        policy = Policy(
            name="Test",
            rules=[
                PolicyRule(
                    id="allow_all",
                    name="Allow all",
                    type=RuleType.ALLOW,
                    match=MatchCondition(),  # Matches everything
                    priority=10,
                ),
                PolicyRule(
                    id="deny_admin",
                    name="Deny admin",
                    type=RuleType.DENY,
                    match=MatchCondition(path_pattern=r".*/admin.*"),
                    priority=100,  # Higher priority
                ),
            ],
        )

        engine = PolicyEngine(policy)

        # Admin path should be denied (higher priority)
        result = engine.evaluate(method="GET", path="/api/admin", host="example.com")
        assert result.allowed is False
        assert result.rule_id == "deny_admin"

        # Non-admin should be allowed
        result = engine.evaluate(method="GET", path="/api/users", host="example.com")
        assert result.allowed is True
        assert result.rule_id == "allow_all"

    def test_evaluate_redaction(self):
        """Test redaction fields are included."""
        policy = Policy(
            name="Test",
            redact_headers=["authorization", "cookie"],
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

        engine = PolicyEngine(policy)
        result = engine.evaluate(method="GET", path="/api/users", host="example.com")

        assert "authorization" in result.redact_fields
        assert "cookie" in result.redact_fields

    def test_evaluate_audit_rule(self):
        """Test audit rule settings."""
        policy = Policy(
            name="Test",
            rules=[
                PolicyRule(
                    id="audit_auth",
                    name="Audit auth",
                    type=RuleType.AUDIT,
                    match=MatchCondition(path_pattern=r".*/auth.*"),
                    priority=100,
                    settings={"level": "detailed"},
                ),
                PolicyRule(
                    id="allow_all",
                    name="Allow all",
                    type=RuleType.ALLOW,
                    match=MatchCondition(),
                    priority=50,
                ),
            ],
        )

        engine = PolicyEngine(policy)
        result = engine.evaluate(method="POST", path="/api/auth/login", host="example.com")

        assert result.allowed is True  # Allow rule still applies
        assert result.audit_level == "detailed"

    def test_budget_reset(self):
        """Test budget reset functionality."""
        policy = Policy(
            name="Test",
            rules=[
                PolicyRule(
                    id="budget_writes",
                    name="Budget writes",
                    type=RuleType.BUDGET,
                    match=MatchCondition(methods=["POST"]),
                    priority=100,
                    settings={"per_minute": 2},
                ),
            ],
        )

        engine = PolicyEngine(policy)

        # Use up budget
        engine.evaluate(method="POST", path="/api", host="example.com")
        engine.evaluate(method="POST", path="/api", host="example.com")

        result = engine.evaluate(method="POST", path="/api", host="example.com")
        assert result.budget_exceeded is True

        # Reset budget
        engine.reset_budget("budget_writes")

        result = engine.evaluate(method="POST", path="/api", host="example.com")
        assert result.allowed is True
        assert result.budget_exceeded is False


class TestPolicyParser:
    """Tests for loading policy from YAML."""

    def test_load_from_yaml(self):
        """Test loading policy from YAML string."""
        yaml_content = """
name: Test Policy
version: "1.0.0"
default_action: deny
audit_all: true
rules:
  - id: allow_get
    name: Allow GET requests
    type: allow
    priority: 100
    match:
      methods:
        - GET
        - HEAD
  - id: deny_admin
    name: Deny admin access
    type: deny
    priority: 200
    match:
      path_pattern: ".*/admin.*"
"""
        engine = PolicyEngine.from_yaml(yaml_content)

        assert engine.policy.name == "Test Policy"
        assert engine.policy.default_action == RuleType.DENY
        assert len(engine.policy.rules) == 2

        # Check that rules work
        result = engine.evaluate(method="GET", path="/api/users", host="example.com")
        assert result.allowed is True

        result = engine.evaluate(method="GET", path="/api/admin", host="example.com")
        assert result.allowed is False

    def test_load_from_file(self, tmp_path):
        """Test loading policy from YAML file."""
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text("""
name: File Policy
default_action: deny
rules:
  - id: allow_all
    name: Allow everything
    type: allow
    match: {}
""")
        engine = PolicyEngine.from_file(str(policy_file))
        assert engine.policy.name == "File Policy"

    def test_load_rejects_unsupported_schema_version(self):
        """Policy parser rejects unsupported schema versions."""
        yaml_content = """
name: Bad Policy
schema_version: "999.0"
default_action: deny
rules: []
"""
        with pytest.raises(ValueError, match="Unsupported policy schema_version"):
            PolicyEngine.from_yaml(yaml_content)
