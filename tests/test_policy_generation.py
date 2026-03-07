"""Tests for policy generation — deny_admin removal (F-032).

The auto-generated deny_admin rule matched .*/admin.* at priority 200,
blocking ALL Shopify endpoints since every path starts with /admin/.
These tests verify that deny_admin is no longer generated, and that
admin endpoints are still accessible through normal policy evaluation.
"""

from toolwright.core.compile.policy import PolicyGenerator
from toolwright.core.enforce import PolicyEngine
from toolwright.models.endpoint import Endpoint
from toolwright.models.policy import Policy


def make_endpoint(
    method: str = "GET",
    path: str = "/api/users/{id}",
    host: str = "api.example.com",
    is_state_changing: bool = False,
    is_auth_related: bool = False,
    has_pii: bool = False,
    risk_tier: str = "low",
) -> Endpoint:
    """Create a test endpoint."""
    return Endpoint(
        method=method,
        path=path,
        host=host,
        is_state_changing=is_state_changing,
        is_auth_related=is_auth_related,
        has_pii=has_pii,
        risk_tier=risk_tier,
    )


class TestNoDenyAdminGeneration:
    """Verify deny_admin rule is NOT auto-generated."""

    def test_no_deny_admin_rule_for_shopify_spec(self):
        """Generated policy for endpoints with /admin/ has NO deny_admin rule."""
        endpoints = [
            make_endpoint(method="GET", path="/admin/api/2024-01/products.json", host="mystore.myshopify.com"),
            make_endpoint(method="POST", path="/admin/api/2024-01/products.json", host="mystore.myshopify.com", is_state_changing=True),
            make_endpoint(method="GET", path="/admin/api/2024-01/orders.json", host="mystore.myshopify.com"),
            make_endpoint(method="DELETE", path="/admin/api/2024-01/products/{id}.json", host="mystore.myshopify.com", is_state_changing=True),
        ]

        generator = PolicyGenerator()
        policy_data = generator.generate(endpoints)

        rule_ids = [r["id"] for r in policy_data["rules"]]
        assert "deny_admin" not in rule_ids, (
            "deny_admin must not be auto-generated — it blocks all Shopify endpoints"
        )

    def test_get_admin_endpoint_evaluates_to_allow(self):
        """GET /admin/api/products evaluates to ALLOW through generated policy."""
        endpoints = [
            make_endpoint(method="GET", path="/admin/api/2024-01/products.json", host="mystore.myshopify.com"),
            make_endpoint(method="POST", path="/admin/api/2024-01/products.json", host="mystore.myshopify.com", is_state_changing=True),
        ]

        generator = PolicyGenerator()
        policy_data = generator.generate(endpoints)

        policy = Policy(**policy_data)
        engine = PolicyEngine(policy)
        result = engine.evaluate(
            method="GET",
            path="/admin/api/2024-01/products.json",
            host="mystore.myshopify.com",
        )

        assert result.allowed is True, (
            f"GET /admin/api/products should be allowed, but got denied: {result.reason}"
        )

    def test_other_generated_rules_still_exist(self):
        """Other auto-generated rules (allow_first_party_get, confirm_state_changes, budget) still generated."""
        endpoints = [
            make_endpoint(method="GET", path="/admin/api/2024-01/products.json", host="mystore.myshopify.com"),
            make_endpoint(method="POST", path="/admin/api/2024-01/products.json", host="mystore.myshopify.com", is_state_changing=True),
            make_endpoint(method="DELETE", path="/admin/api/2024-01/products/{id}.json", host="mystore.myshopify.com", is_state_changing=True),
        ]

        generator = PolicyGenerator()
        policy_data = generator.generate(endpoints)

        rule_ids = [r["id"] for r in policy_data["rules"]]

        assert "allow_first_party_get" in rule_ids, "allow_first_party_get rule should still be generated"
        assert "confirm_state_changes" in rule_ids, "confirm_state_changes rule should still be generated"
        assert "budget_writes" in rule_ids, "budget_writes rule should still be generated"
        assert "budget_deletes" in rule_ids, "budget_deletes rule should still be generated"
