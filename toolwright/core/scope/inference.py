"""Scope inference engine — compute ScopeDraft entries from endpoints.

4-stage pipeline per docs/architecture.md §6.3:
1. Structural classification (HTTP method → scope)
2. Semantic signal scoring (path keywords, auth, PII, tags)
3. Risk tier assignment (critical/high/medium/low/safe)
4. Conservative defaults (review_required when uncertain)
"""

from __future__ import annotations

import re

from toolwright.core.risk_keywords import CRITICAL_PATH_KEYWORDS, HIGH_RISK_PATH_KEYWORDS
from toolwright.models.endpoint import Endpoint
from toolwright.models.scope import RiskReason, ScopeDraft

# Search-like POST patterns (POST but semantically read-only)
_SEARCH_PATH_PATTERN = re.compile(
    r"(search|query|graphql|lookup|filter|autocomplete|suggest)",
    re.IGNORECASE,
)


class ScopeInferenceEngine:
    """Infer scope assignments with confidence scoring for endpoints."""

    def infer(self, endpoints: list[Endpoint]) -> list[ScopeDraft]:
        """Run the 4-stage inference pipeline on a list of endpoints."""
        return [self._infer_one(ep) for ep in endpoints]

    def _infer_one(self, ep: Endpoint) -> ScopeDraft:
        endpoint_id = ep.signature_id or ep.tool_id or ep.id

        # Stage 1: Structural classification
        scope_name = self._classify_structure(ep)

        # Stage 2: Semantic signal scoring
        signals: list[str] = []
        risk_reasons: list[RiskReason] = []
        confidence = self._score_confidence(ep, scope_name, signals, risk_reasons)

        # Stage 3: Risk tier assignment
        risk_tier = self._assign_risk_tier(ep, risk_reasons)

        # Stage 4: Conservative defaults (review_required handled by ScopeDraft.model_post_init)
        explanation = self._build_explanation(scope_name, risk_tier, signals)

        return ScopeDraft(
            endpoint_id=endpoint_id,
            scope_name=scope_name,
            confidence=round(confidence, 3),
            risk_tier=risk_tier,
            risk_reasons=risk_reasons,
            signals=signals,
            explanation=explanation,
        )

    def _classify_structure(self, ep: Endpoint) -> str:
        """Stage 1: Method-based structural classification."""
        method_upper = ep.method.upper()
        tag_set = {str(tag).lower() for tag in ep.tags}

        if method_upper == "GET":
            return "read"

        if method_upper == "POST":
            # Tags should override path heuristics (especially for GraphQL op-split actions).
            if "write" in tag_set or "graphql:mutation" in tag_set:
                return "write"
            if "read" in tag_set or "graphql:query" in tag_set:
                return "read"

            # POST to search/query/graphql paths = read
            if _SEARCH_PATH_PATTERN.search(ep.path):
                return "read"
            return "write"

        if method_upper == "DELETE":
            return "delete"

        if method_upper in ("PUT", "PATCH"):
            return "write"

        return "read"  # HEAD, OPTIONS, etc.

    def _score_confidence(
        self,
        ep: Endpoint,
        scope_name: str,
        signals: list[str],
        risk_reasons: list[RiskReason],
    ) -> float:
        """Stage 2: Weighted signal scoring."""
        score = 0.6  # Base confidence

        # Simple reads (GET, first-party, no risk signals) are high confidence
        if ep.method.upper() == "GET" and ep.is_first_party and not ep.is_auth_related:
            score += 0.15

        # Signal 1: Path keywords (weight 0.3)
        if CRITICAL_PATH_KEYWORDS.search(ep.path):
            signals.append(f"critical path keyword in {ep.path}")
            risk_reasons.append(RiskReason.SENSITIVE_PATH)
            score += 0.15  # We're more certain about the classification

        if HIGH_RISK_PATH_KEYWORDS.search(ep.path):
            signals.append(f"high-risk path keyword in {ep.path}")
            risk_reasons.append(RiskReason.SENSITIVE_PATH)
            score += 0.1

        # Signal 2: Auth-related (weight 0.2)
        if ep.is_auth_related:
            signals.append("auth-related endpoint")
            risk_reasons.append(RiskReason.AUTH_RELATED)
            score += 0.1

        # Signal 3: PII fields (weight 0.2)
        if ep.has_pii:
            signals.append("PII fields detected")
            risk_reasons.append(RiskReason.HAS_PII)
            score += 0.05

        # Signal 4: State-changing method (weight 0.15)
        if ep.method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            signals.append(f"state-changing method: {ep.method}")
            risk_reasons.append(RiskReason.STATE_CHANGING)
            score += 0.1

        # Signal 5: Domain tags (weight 0.15)
        tag_set = set(ep.tags)
        if "commerce" in tag_set or "auth" in tag_set:
            signals.append(f"domain tags: {', '.join(tag_set & {'commerce', 'auth'})}")
            score += 0.1

        # Signal 6: Third-party
        if not ep.is_first_party:
            signals.append("third-party endpoint")
            risk_reasons.append(RiskReason.THIRD_PARTY)
            score -= 0.1  # Less certain about third-party endpoints

        # Signal 7: Write operations
        if scope_name in ("write", "delete"):
            risk_reasons.append(RiskReason.WRITE_OPERATION)

        # Clamp to [0.1, 0.95]
        return max(0.1, min(0.95, score))

    def _assign_risk_tier(
        self,
        ep: Endpoint,
        risk_reasons: list[RiskReason],
    ) -> str:
        """Stage 3: Risk tier assignment based on accumulated signals."""
        reason_set = set(risk_reasons)
        method_upper = ep.method.upper()

        inferred = "safe"

        # Critical: auth/payment/admin endpoints
        if RiskReason.AUTH_RELATED in reason_set:
            inferred = "critical"
        elif RiskReason.SENSITIVE_PATH in reason_set and (
            method_upper != "GET" or CRITICAL_PATH_KEYWORDS.search(ep.path)
        ):
            # GET on admin/payment is still critical.
            inferred = "critical"

        # High: write with PII, delete operations
        elif (
            RiskReason.WRITE_OPERATION in reason_set and RiskReason.HAS_PII in reason_set
        ) or method_upper == "DELETE":
            inferred = "high"

        # Medium: write without PII, third-party reads
        elif RiskReason.WRITE_OPERATION in reason_set or RiskReason.THIRD_PARTY in reason_set:
            inferred = "medium"

        # Low: first-party reads with PII
        elif RiskReason.HAS_PII in reason_set:
            inferred = "low"

        # Never under-classify relative to the endpoint's own risk tier, if present.
        risk_rank = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        endpoint_risk = str(ep.risk_tier or "").strip().lower()
        # Only respect explicit medium+ risk upgrades; many Endpoint instances use
        # a default `low` placeholder, and we do not want to erase true "safe" reads.
        if endpoint_risk not in {"medium", "high", "critical"}:
            return inferred
        if risk_rank[endpoint_risk] > risk_rank[inferred]:
            return endpoint_risk
        return inferred

    def _build_explanation(
        self,
        scope_name: str,
        risk_tier: str,
        signals: list[str],
    ) -> str:
        """Build a human-readable explanation of the inference."""
        parts = [f"Classified as '{scope_name}' (risk: {risk_tier})"]
        if signals:
            parts.append(f"Signals: {'; '.join(signals)}")
        return ". ".join(parts)
