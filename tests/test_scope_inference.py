"""Tests for ScopeInferenceEngine."""

from __future__ import annotations

from toolwright.core.scope.inference import ScopeInferenceEngine
from toolwright.models.endpoint import Endpoint
from toolwright.models.scope import RiskReason


def _ep(
    method: str = "GET",
    path: str = "/api/items",
    host: str = "api.example.com",
    is_auth_related: bool = False,
    has_pii: bool = False,
    is_first_party: bool = True,
    tags: list[str] | None = None,
    response_body_schema: dict | None = None,
    request_body_schema: dict | None = None,
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host=host,
        is_auth_related=is_auth_related,
        has_pii=has_pii,
        is_first_party=is_first_party,
        tags=tags or [],
        response_body_schema=response_body_schema,
        request_body_schema=request_body_schema,
    )


class TestStructuralClassification:
    def test_get_classified_as_read(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="GET")])
        assert len(drafts) == 1
        assert drafts[0].scope_name == "read"

    def test_post_classified_as_write(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="POST", path="/api/items")])
        assert drafts[0].scope_name == "write"

    def test_post_search_classified_as_read(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="POST", path="/api/search")])
        assert drafts[0].scope_name == "read"

    def test_delete_classified_as_delete(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="DELETE", path="/api/items/{id}")])
        assert drafts[0].scope_name == "delete"

    def test_put_classified_as_write(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="PUT", path="/api/items/{id}")])
        assert drafts[0].scope_name == "write"

    def test_patch_classified_as_write(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="PATCH", path="/api/items/{id}")])
        assert drafts[0].scope_name == "write"


class TestRiskTierAssignment:
    def test_auth_endpoint_is_critical(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(path="/api/auth/login", is_auth_related=True)])
        assert drafts[0].risk_tier == "critical"
        assert RiskReason.AUTH_RELATED in drafts[0].risk_reasons

    def test_payment_path_is_critical(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(path="/api/payments/{id}", method="POST")])
        assert drafts[0].risk_tier == "critical"
        assert RiskReason.SENSITIVE_PATH in drafts[0].risk_reasons

    def test_admin_path_is_critical(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(path="/api/admin/users")])
        assert drafts[0].risk_tier == "critical"

    def test_write_with_pii_is_high(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="POST", path="/api/users", has_pii=True)])
        assert drafts[0].risk_tier == "high"
        assert RiskReason.HAS_PII in drafts[0].risk_reasons
        assert RiskReason.WRITE_OPERATION in drafts[0].risk_reasons

    def test_delete_is_high(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="DELETE", path="/api/items/{id}")])
        assert drafts[0].risk_tier in ("high", "critical")

    def test_first_party_read_without_pii_is_safe(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="GET", path="/api/products")])
        assert drafts[0].risk_tier == "safe"

    def test_first_party_read_with_pii_is_low(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="GET", path="/api/users", has_pii=True)])
        assert drafts[0].risk_tier == "low"

    def test_third_party_read_is_medium(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="GET", path="/api/data", is_first_party=False)])
        assert drafts[0].risk_tier == "medium"


class TestConfidenceScoring:
    def test_simple_get_has_high_confidence(self) -> None:
        engine = ScopeInferenceEngine()
        drafts = engine.infer([_ep(method="GET", path="/api/products")])
        assert drafts[0].confidence >= 0.7

    def test_ambiguous_post_has_lower_confidence(self) -> None:
        engine = ScopeInferenceEngine()
        # POST without clear search path — ambiguous
        drafts = engine.infer([_ep(method="POST", path="/api/process")])
        # Should still be reasonable
        assert 0.4 <= drafts[0].confidence <= 1.0

    def test_low_confidence_high_risk_requires_review(self) -> None:
        """confidence < 0.7 AND risk high/critical → review_required."""
        engine = ScopeInferenceEngine()
        # Auth endpoint with ambiguous signals
        drafts = engine.infer([_ep(
            method="POST",
            path="/api/admin/refund",
            is_auth_related=True,
            has_pii=True,
            is_first_party=False,
        )])
        draft = drafts[0]
        assert draft.risk_tier in ("high", "critical")
        # ScopeDraft.model_post_init auto-sets review_required
        if draft.confidence < 0.7:
            assert draft.review_required is True


class TestMultipleEndpoints:
    def test_infer_multiple_endpoints(self) -> None:
        engine = ScopeInferenceEngine()
        endpoints = [
            _ep(method="GET", path="/api/products"),
            _ep(method="POST", path="/api/orders"),
            _ep(method="DELETE", path="/api/orders/{id}"),
        ]
        drafts = engine.infer(endpoints)
        assert len(drafts) == 3
        scopes = {d.scope_name for d in drafts}
        assert "read" in scopes
        assert "write" in scopes
        assert "delete" in scopes

    def test_endpoint_ids_match(self) -> None:
        engine = ScopeInferenceEngine()
        ep = _ep(method="GET", path="/api/products")
        drafts = engine.infer([ep])
        assert drafts[0].endpoint_id == (ep.signature_id or ep.tool_id or ep.id)
