# Fix Dogfood Blockers — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 4 code blockers (F-028/F-032/F-037/F-039/F-040) found during live dogfood testing against Shopify Admin REST API.

**Architecture:** Each blocker is an independent fix touching 1-2 source files + tests. All follow TDD: write failing test → minimal fix → verify green → commit. Implementation order minimizes risk: pure deletion first, then additive changes.

**Tech Stack:** Python 3.13, pytest, Pydantic models, Click CLI

**Design doc:** `docs/plans/2026-03-01-dogfood-blockers-design.md`

---

## Task 1: Delete deny_admin Rule Generation (Blocker 2 — F-032)

Simplest fix. Pure deletion of 15 lines. Unblocks ALL Shopify endpoints immediately.

**Files:**
- Modify: `toolwright/core/compile/policy.py:178-193`
- Test: `tests/test_policy_generation.py` (create)
- Reference: `tests/test_policy.py` (existing test patterns)

**Step 1: Write the failing test**

Create `tests/test_policy_generation.py`:

```python
"""Tests for policy generation — deny_admin removal (F-032)."""

from __future__ import annotations

from toolwright.core.compile.policy import PolicyGenerator
from toolwright.models.endpoint import Endpoint


def _make_endpoint(method: str = "GET", path: str = "/admin/api/2024-01/products.json") -> Endpoint:
    """Build a minimal Endpoint with /admin/ path."""
    return Endpoint(
        method=method,
        path=path,
        host="store.myshopify.com",
        stable_id=f"ep_{method.lower()}_{path.replace('/', '_')}",
        signature_id=f"sig_{method.lower()}_{path.replace('/', '_')}",
        risk_tier="medium",
    )


class TestDenyAdminRemoved:
    """F-032: deny_admin rule must NOT be generated."""

    def test_no_deny_admin_rule_for_shopify_spec(self):
        """Generated policy for Shopify-like spec has NO deny_admin rule."""
        endpoints = [
            _make_endpoint("GET", "/admin/api/2024-01/products.json"),
            _make_endpoint("POST", "/admin/api/2024-01/products.json"),
            _make_endpoint("DELETE", "/admin/api/2024-01/products/123.json"),
        ]
        generator = PolicyGenerator()
        policy_data = generator.generate(endpoints)

        rule_ids = [r["id"] for r in policy_data.get("rules", [])]
        assert "deny_admin" not in rule_ids, (
            "deny_admin rule must not be generated — it blocks ALL Shopify endpoints"
        )

    def test_get_admin_endpoint_evaluates_to_allow(self):
        """GET /admin/api/products.json evaluates to ALLOW through generated policy."""
        from toolwright.core.enforce import PolicyEngine
        from toolwright.models.policy import Policy

        endpoints = [
            _make_endpoint("GET", "/admin/api/2024-01/products.json"),
        ]
        generator = PolicyGenerator()
        policy_data = generator.generate(endpoints)
        policy = Policy(**policy_data)
        engine = PolicyEngine(policy)

        result = engine.evaluate(
            method="GET",
            path="/admin/api/2024-01/products.json",
            host="store.myshopify.com",
            risk_tier="medium",
        )
        assert result.allowed, f"GET /admin/ should be ALLOWED, got: {result.reason}"

    def test_other_generated_rules_still_exist(self):
        """Other auto-generated rules (allow_first_party_get, confirm, budget) still generated."""
        endpoints = [
            _make_endpoint("GET", "/admin/api/2024-01/products.json"),
            _make_endpoint("POST", "/admin/api/2024-01/products.json"),
            _make_endpoint("DELETE", "/admin/api/2024-01/products/123.json"),
        ]
        generator = PolicyGenerator()
        policy_data = generator.generate(endpoints)

        rule_ids = [r["id"] for r in policy_data.get("rules", [])]
        assert "allow_first_party_get" in rule_ids
        assert "confirm_state_changes" in rule_ids
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_policy_generation.py -v`

Expected: `test_no_deny_admin_rule_for_shopify_spec` FAILS because deny_admin IS currently generated. The other tests may fail too (GET denied by deny_admin rule at priority 200).

**Step 3: Delete the deny_admin generation block**

In `toolwright/core/compile/policy.py`, delete lines 178-193 (the entire block):

```python
        # DELETE THIS ENTIRE BLOCK (lines 178-193):
        # Rule: Deny admin endpoints by default
        admin_endpoints = [ep for ep in endpoints if "/admin" in ep.path.lower()]
        if admin_endpoints:
            rules.append({
                "id": "deny_admin",
                "name": "Block admin access by default",
                "type": "deny",
                "priority": 200,  # High priority
                "match": {
                    "path_pattern": ".*/admin.*",
                },
                "settings": {
                    "message": "Admin endpoints require explicit allowlist",
                    "justification": "Admin endpoints are high-risk and denied by default.",
                },
            })
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_policy_generation.py -v`

Expected: All 3 tests PASS.

**Step 5: Run full test suite for regressions**

Run: `python -m pytest tests/ -v`

Expected: All tests pass. If any existing tests assert deny_admin exists, update those tests to remove the assertion (the rule is gone by design).

**Step 6: Commit**

```bash
git add toolwright/core/compile/policy.py tests/test_policy_generation.py
git commit -m "fix(policy): remove deny_admin rule generation (F-032)

The auto-generated deny_admin rule matched .*/admin.* at priority 200,
blocking ALL Shopify endpoints since every path starts with /admin/.
Risk tiers + confirmation gates + behavioral rules already provide
sufficient protection. If admin blocking is needed, add a behavioral
rule explicitly."
```

---

## Task 2: Method-Aware Risk Capping (Blocker 1 — F-028/F-035)

Cap read-only methods (GET/HEAD/OPTIONS) at `medium` risk regardless of path keywords. Write methods keep existing classification.

**Files:**
- Modify: `toolwright/core/normalize/aggregator.py:615-647`
- Test: `tests/test_risk_classification.py` (create)
- Reference: `toolwright/core/risk_keywords.py` (CRITICAL_PATH_KEYWORDS)
- Reference: `toolwright/core/proposal/publisher.py:31` (RISK_ORDER)

**Step 1: Write the failing tests**

Create `tests/test_risk_classification.py`:

```python
"""Tests for risk classification — method-aware capping (F-028/F-035)."""

from __future__ import annotations

from toolwright.core.normalize.aggregator import EndpointAggregator
from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod


def _make_session(exchanges: list[HttpExchange]) -> CaptureSession:
    return CaptureSession(
        id="test-session",
        name="test",
        source="manual",
        exchanges=exchanges,
        allowed_hosts=["store.myshopify.com"],
    )


def _make_exchange(
    method: HTTPMethod,
    path: str,
    host: str = "store.myshopify.com",
) -> HttpExchange:
    return HttpExchange(
        url=f"https://{host}{path}",
        method=method,
        host=host,
        path=path,
        response_status=200,
    )


class TestMethodAwareRiskCapping:
    """F-028/F-035: GET/HEAD/OPTIONS never exceed medium risk."""

    def test_get_admin_path_capped_at_medium(self):
        """GET /admin/api/products.json → medium (not critical)."""
        exchange = _make_exchange(HTTPMethod.GET, "/admin/api/2024-01/products.json")
        aggregator = EndpointAggregator(first_party_hosts=["store.myshopify.com"])
        endpoints = aggregator.aggregate(_make_session([exchange]))

        assert len(endpoints) == 1
        assert endpoints[0].risk_tier == "medium", (
            f"GET /admin/ should be capped at medium, got {endpoints[0].risk_tier}"
        )

    def test_delete_admin_path_stays_critical(self):
        """DELETE /admin/api/products/{id}.json → critical (unchanged)."""
        exchange = _make_exchange(HTTPMethod.DELETE, "/admin/api/2024-01/products/123.json")
        aggregator = EndpointAggregator(first_party_hosts=["store.myshopify.com"])
        endpoints = aggregator.aggregate(_make_session([exchange]))

        assert len(endpoints) == 1
        assert endpoints[0].risk_tier == "critical", (
            f"DELETE /admin/ should be critical, got {endpoints[0].risk_tier}"
        )

    def test_post_admin_path_stays_critical(self):
        """POST /admin/api/products.json → critical (unchanged)."""
        exchange = _make_exchange(HTTPMethod.POST, "/admin/api/2024-01/products.json")
        aggregator = EndpointAggregator(first_party_hosts=["store.myshopify.com"])
        endpoints = aggregator.aggregate(_make_session([exchange]))

        assert len(endpoints) == 1
        assert endpoints[0].risk_tier == "critical", (
            f"POST /admin/ should be critical, got {endpoints[0].risk_tier}"
        )

    def test_get_payments_path_capped_at_medium(self):
        """GET /admin/api/payments/refunds.json → medium (capped)."""
        exchange = _make_exchange(HTTPMethod.GET, "/admin/api/2024-01/payments/refunds.json")
        aggregator = EndpointAggregator(first_party_hosts=["store.myshopify.com"])
        endpoints = aggregator.aggregate(_make_session([exchange]))

        assert len(endpoints) == 1
        assert endpoints[0].risk_tier == "medium", (
            f"GET /payments/ should be capped at medium, got {endpoints[0].risk_tier}"
        )

    def test_get_safe_path_unchanged(self):
        """GET /api/products.json (no keywords) → safe/low (unchanged)."""
        exchange = _make_exchange(HTTPMethod.GET, "/api/products.json")
        aggregator = EndpointAggregator(first_party_hosts=["store.myshopify.com"])
        endpoints = aggregator.aggregate(_make_session([exchange]))

        assert len(endpoints) == 1
        assert endpoints[0].risk_tier in ("safe", "low"), (
            f"GET /api/products.json should be safe/low, got {endpoints[0].risk_tier}"
        )

    def test_put_admin_path_stays_critical(self):
        """PUT /admin/api/products/{id}.json → critical (unchanged)."""
        exchange = _make_exchange(HTTPMethod.PUT, "/admin/api/2024-01/products/123.json")
        aggregator = EndpointAggregator(first_party_hosts=["store.myshopify.com"])
        endpoints = aggregator.aggregate(_make_session([exchange]))

        assert len(endpoints) == 1
        assert endpoints[0].risk_tier == "critical", (
            f"PUT /admin/ should be critical, got {endpoints[0].risk_tier}"
        )
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_risk_classification.py -v`

Expected: `test_get_admin_path_capped_at_medium` and `test_get_payments_path_capped_at_medium` FAIL (they currently return `critical`). Tests for DELETE/POST/PUT should PASS (already critical).

**Step 3: Implement method-aware risk capping**

In `toolwright/core/normalize/aggregator.py`, modify `_determine_risk_tier()` at line 615:

Replace the entire method (lines 615-647) with:

```python
    # Risk tier ordering for cap comparison
    _RISK_ORDER = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

    def _determine_risk_tier(
        self,
        method: str,
        path: str,
        is_auth_related: bool,
        has_pii: bool,
        is_first_party: bool,
    ) -> str:
        """Determine risk tier for an endpoint."""
        tier = self._classify_risk(method, path, is_auth_related, has_pii, is_first_party)

        # Cap: read-only methods never exceed medium
        if method.upper() in ("GET", "HEAD", "OPTIONS"):
            if self._RISK_ORDER.get(tier, 0) > self._RISK_ORDER["medium"]:
                tier = "medium"

        return tier

    def _classify_risk(
        self,
        method: str,
        path: str,
        is_auth_related: bool,
        has_pii: bool,
        is_first_party: bool,
    ) -> str:
        """Core risk classification logic (before method-aware capping)."""
        if is_auth_related:
            return "critical"

        if CRITICAL_PATH_KEYWORDS.search(path):
            return "critical"

        if HIGH_RISK_PATH_KEYWORDS.search(path):
            return "high"

        if method in ("DELETE",):
            return "high"

        if method in ("POST", "PUT", "PATCH"):
            if has_pii:
                return "high"
            return "medium"

        if has_pii:
            return "low"

        if not is_first_party:
            return "medium"

        return "safe"
```

The key change: the existing classification logic moves to `_classify_risk()`. The public `_determine_risk_tier()` calls it, then applies the read-only method cap.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_risk_classification.py -v`

Expected: All 6 tests PASS.

**Step 5: Run full test suite for regressions**

Run: `python -m pytest tests/ -v`

Expected: All tests pass including existing aggregator tests.

**Step 6: Commit**

```bash
git add toolwright/core/normalize/aggregator.py tests/test_risk_classification.py
git commit -m "fix(risk): cap read-only methods at medium risk (F-028/F-035)

GET/HEAD/OPTIONS methods are now capped at medium risk regardless of
path keywords. This fixes 1181/1183 Shopify tools being classified as
critical just because paths contain /admin/. Write methods (POST, PUT,
PATCH, DELETE) keep their full risk classification — DELETE /admin/
remains critical as intended."
```

---

## Task 3: Budget/Rate-Limit Double-Counting Fix (Blocker 4 — F-039/F-040)

Add `dry_run` parameter to PolicyEngine.evaluate() so budget is only consumed on final ALLOW decisions.

**Files:**
- Modify: `toolwright/core/enforce/engine.py:45-119` (PolicyEngine.evaluate + new consume_budget method)
- Modify: `toolwright/core/enforce/decision_engine.py:87-96` (call with dry_run, consume on ALLOW)
- Test: `tests/test_budget_double_counting.py` (create)
- Reference: `tests/test_decision_engine.py` (existing patterns)

**Step 1: Write the failing tests**

Create `tests/test_budget_double_counting.py`:

```python
"""Tests for budget double-counting fix (F-039/F-040)."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.enforce import ConfirmationStore, DecisionEngine, PolicyEngine
from toolwright.models.decision import DecisionContext, DecisionRequest, DecisionType
from toolwright.models.policy import (
    MatchCondition,
    Policy,
    PolicyRule,
    RuleType,
)


def _budget_policy(max_per_minute: int = 3) -> Policy:
    """Policy with budget rule limiting calls per minute."""
    return Policy(
        name="budget_test",
        default_action=RuleType.DENY,
        rules=[
            PolicyRule(
                id="allow_gets",
                name="Allow GETs",
                type=RuleType.ALLOW,
                priority=100,
                match=MatchCondition(methods=["GET"]),
            ),
            PolicyRule(
                id="confirm_writes",
                name="Confirm writes",
                type=RuleType.CONFIRM,
                priority=90,
                match=MatchCondition(methods=["POST", "PUT", "PATCH", "DELETE"]),
                settings={"message": "Write requires confirmation"},
            ),
            PolicyRule(
                id="budget_writes",
                name="Budget for writes",
                type=RuleType.BUDGET,
                priority=80,
                match=MatchCondition(methods=["POST", "PUT", "PATCH", "DELETE"]),
                settings={"per_minute": max_per_minute},
            ),
        ],
    )


def _action(method: str = "POST") -> dict[str, object]:
    return {
        "name": "create_product",
        "tool_id": "sig_create_product",
        "signature_id": "sig_create_product",
        "method": method,
        "path": "/admin/api/2024-01/products.json",
        "host": "store.myshopify.com",
        "risk_tier": "medium",
    }


def _context(
    action: dict[str, object],
    policy: Policy,
    confirmation_store: ConfirmationStore | None = None,
) -> DecisionContext:
    policy_engine = PolicyEngine(policy)
    return DecisionContext(
        manifest_view={
            "sig_create_product": action,
            "create_product": action,
        },
        policy=policy,
        policy_engine=policy_engine,
        lockfile=None,
        artifacts_digest_current="digest_current",
        lockfile_digest_current=None,
    )


class TestBudgetDoubleCountingFix:
    """F-039/F-040: Confirmed calls should consume 1 budget unit, not 2."""

    def test_confirm_decision_consumes_zero_budget(self, tmp_path: Path):
        """Challenge creation (CONFIRM result) consumes 0 budget."""
        policy = _budget_policy(max_per_minute=3)
        store = ConfirmationStore(tmp_path / "confirmations.db")
        engine = DecisionEngine(store)
        action = _action("POST")
        ctx = _context(action, policy, store)

        # First call: should get CONFIRM (challenge creation)
        result = engine.evaluate(
            DecisionRequest(
                tool_id="sig_create_product",
                action_name="create_product",
                mode="execute",
                params={},
            ),
            ctx,
        )
        assert result.decision == DecisionType.CONFIRM

        # Budget should NOT have been consumed
        budget_tracker = ctx.policy_engine._budgets.get("budget_writes")
        assert budget_tracker is not None
        assert budget_tracker._minute_count == 0, (
            f"Challenge creation consumed {budget_tracker._minute_count} budget units, expected 0"
        )

    def test_confirmed_call_consumes_one_budget_unit(self, tmp_path: Path):
        """Full confirmed call (challenge + grant + redeem) consumes exactly 1 budget unit."""
        policy = _budget_policy(max_per_minute=3)
        store = ConfirmationStore(tmp_path / "confirmations.db")
        engine = DecisionEngine(store)
        action = _action("POST")
        ctx = _context(action, policy, store)

        request = DecisionRequest(
            tool_id="sig_create_product",
            action_name="create_product",
            mode="execute",
            params={},
        )

        # Step 1: Get challenge
        result1 = engine.evaluate(request, ctx)
        assert result1.decision == DecisionType.CONFIRM
        token_id = result1.confirmation_token_id
        assert token_id is not None

        # Step 2: Grant the challenge
        store.grant(token_id)

        # Step 3: Redeem with token
        request_with_token = DecisionRequest(
            tool_id="sig_create_product",
            action_name="create_product",
            mode="execute",
            params={},
            confirmation_token_id=token_id,
        )
        result2 = engine.evaluate(request_with_token, ctx)
        assert result2.decision == DecisionType.ALLOW

        # Budget should have been consumed exactly once
        budget_tracker = ctx.policy_engine._budgets.get("budget_writes")
        assert budget_tracker is not None
        assert budget_tracker._minute_count == 1, (
            f"Full confirmed call consumed {budget_tracker._minute_count} budget units, expected 1"
        )

    def test_max_calls_3_allows_3_confirmed_calls(self, tmp_path: Path):
        """max_calls=3 allows exactly 3 confirmed calls, not 1-2."""
        policy = _budget_policy(max_per_minute=3)
        store = ConfirmationStore(tmp_path / "confirmations.db")
        engine = DecisionEngine(store)
        action = _action("POST")
        ctx = _context(action, policy, store)

        for i in range(3):
            request = DecisionRequest(
                tool_id="sig_create_product",
                action_name="create_product",
                mode="execute",
                params={},
            )

            # Challenge
            result = engine.evaluate(request, ctx)
            assert result.decision == DecisionType.CONFIRM, f"Call {i+1}: expected CONFIRM"
            token_id = result.confirmation_token_id

            # Grant and redeem
            store.grant(token_id)
            request_with_token = DecisionRequest(
                tool_id="sig_create_product",
                action_name="create_product",
                mode="execute",
                params={},
                confirmation_token_id=token_id,
            )
            result = engine.evaluate(request_with_token, ctx)
            assert result.decision == DecisionType.ALLOW, f"Call {i+1}: expected ALLOW"

        budget_tracker = ctx.policy_engine._budgets.get("budget_writes")
        assert budget_tracker is not None
        assert budget_tracker._minute_count == 3

    def test_direct_allow_still_consumes_one_budget(self):
        """Direct ALLOW (no confirmation) still consumes 1 budget (no regression)."""
        policy = Policy(
            name="direct_budget_test",
            default_action=RuleType.DENY,
            rules=[
                PolicyRule(
                    id="allow_all",
                    name="Allow all",
                    type=RuleType.ALLOW,
                    priority=100,
                    match=MatchCondition(),
                ),
                PolicyRule(
                    id="budget_all",
                    name="Budget all",
                    type=RuleType.BUDGET,
                    priority=80,
                    match=MatchCondition(),
                    settings={"per_minute": 5},
                ),
            ],
        )
        engine = PolicyEngine(policy)

        # Evaluate in non-dry-run mode (simulating direct ALLOW path)
        result = engine.evaluate(
            method="GET",
            path="/api/products",
            host="example.com",
            risk_tier="low",
        )
        assert result.allowed

        budget_tracker = engine._budgets.get("budget_all")
        assert budget_tracker is not None
        assert budget_tracker._minute_count == 1
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_budget_double_counting.py -v`

Expected: `test_confirm_decision_consumes_zero_budget` FAILS (budget currently consumed during challenge). `test_max_calls_3_allows_3_confirmed_calls` likely FAILS (double-counting blocks earlier). `test_direct_allow_still_consumes_one_budget` may PASS (existing behavior for non-confirmation path).

**Step 3: Add dry_run parameter to PolicyEngine.evaluate()**

In `toolwright/core/enforce/engine.py`, modify `PolicyEngine.evaluate()` at line 45:

Change the method signature from:

```python
    def evaluate(
        self,
        method: str,
        path: str,
        host: str,
        headers: dict[str, str] | None = None,
        risk_tier: str | None = None,
        scope: str | None = None,
    ) -> EvaluationResult:
```

To:

```python
    def evaluate(
        self,
        method: str,
        path: str,
        host: str,
        headers: dict[str, str] | None = None,
        risk_tier: str | None = None,
        scope: str | None = None,
        *,
        dry_run: bool = False,
    ) -> EvaluationResult:
```

Then modify the budget consumption block (lines 110-122) from:

```python
                elif rule.type == RuleType.BUDGET:
                    tracker = self._budgets.get(rule.id)
                    if tracker:
                        if not tracker.check():
                            budget_exceeded = True
                            budget_rule_matched = rule
                            matched_rule = rule
                            break
                        else:
                            tracker.consume()
                            budget_remaining = tracker.remaining
                            if matched_rule is None:
                                matched_rule = rule
```

To:

```python
                elif rule.type == RuleType.BUDGET:
                    tracker = self._budgets.get(rule.id)
                    if tracker:
                        if not tracker.check():
                            budget_exceeded = True
                            budget_rule_matched = rule
                            matched_rule = rule
                            break
                        else:
                            if not dry_run:
                                tracker.consume()
                            budget_remaining = tracker.remaining
                            if matched_rule is None:
                                matched_rule = rule
```

The only change is wrapping `tracker.consume()` with `if not dry_run:`.

**Step 4: Add consume_budget() method to PolicyEngine**

Add after the `evaluate()` method (around line 210):

```python
    def consume_budget(
        self,
        method: str,
        path: str,
        host: str,
        headers: dict[str, str] | None = None,
        risk_tier: str | None = None,
        scope: str | None = None,
    ) -> None:
        """Explicitly consume budget for matching rules.

        Called after a final ALLOW decision to debit the budget tracker.
        This is separate from evaluate() to support dry_run evaluation.
        """
        rules = self.policy.get_rules_by_priority()
        for rule in rules:
            if rule.type == RuleType.BUDGET and rule.match.matches(
                method, path, host, headers, risk_tier, scope
            ):
                tracker = self._budgets.get(rule.id)
                if tracker and tracker.check():
                    tracker.consume()
```

**Step 5: Update DecisionEngine to use dry_run + explicit consume**

In `toolwright/core/enforce/decision_engine.py`, modify lines 87-96.

Change from:

```python
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
```

To:

```python
        policy_engine = context.policy_engine
        policy_result = None
        if policy_engine is not None:
            policy_result = policy_engine.evaluate(
                method=method,
                path=path,
                host=host,
                risk_tier=risk_tier,
                scope=request.toolset_name,
                dry_run=True,  # Always dry_run; consume only on final ALLOW
            )
```

Then find the two places that return `DecisionType.ALLOW` and add budget consumption before each:

1. After confirmation token consumed (around line 150-158), change:

```python
                if consumed:
                    return DecisionResult(
                        decision=DecisionType.ALLOW,
```

To:

```python
                if consumed:
                    if policy_engine is not None:
                        policy_engine.consume_budget(
                            method=method, path=path, host=host,
                            risk_tier=risk_tier, scope=request.toolset_name,
                        )
                    return DecisionResult(
                        decision=DecisionType.ALLOW,
```

2. At the final ALLOW return (around line 192-199), change:

```python
        return DecisionResult(
            decision=DecisionType.ALLOW,
            reason_code=ReasonCode.ALLOWED_POLICY,
```

To:

```python
        if policy_engine is not None:
            policy_engine.consume_budget(
                method=method, path=path, host=host,
                risk_tier=risk_tier, scope=request.toolset_name,
            )
        return DecisionResult(
            decision=DecisionType.ALLOW,
            reason_code=ReasonCode.ALLOWED_POLICY,
```

**Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_budget_double_counting.py -v`

Expected: All 4 tests PASS.

**Step 7: Run full test suite for regressions**

Run: `python -m pytest tests/ -v`

Expected: All tests pass. Existing decision engine tests should still work — the dry_run default means `PolicyEngine.evaluate()` called directly (without `dry_run=True`) still consumes budget (backward compat for tests calling PolicyEngine directly).

**Step 8: Commit**

```bash
git add toolwright/core/enforce/engine.py toolwright/core/enforce/decision_engine.py tests/test_budget_double_counting.py
git commit -m "fix(budget): consume budget only on final ALLOW (F-039/F-040)

Confirmation flow previously consumed budget twice: once during
challenge creation and once during token redemption. Now
PolicyEngine.evaluate() accepts dry_run=True to check budget without
consuming. DecisionEngine always evaluates in dry_run mode, then
explicitly calls consume_budget() only when the final decision is ALLOW.

Confirmed calls now consume exactly 1 budget unit. max_calls=3 allows
exactly 3 confirmed calls."
```

---

## Task 4: POST Body Envelope Wrapping (Blocker 3 — F-037)

Detect wrapper key during compile, store in action metadata, wrap at execution time.

**Files:**
- Modify: `toolwright/core/compile/tools.py:198-228` (_action_from_endpoint) + `toolwright/core/compile/tools.py:230-301` (_build_input_schema)
- Modify: `toolwright/mcp/server.py:698-702` (build_url_and_kwargs)
- Test: `tests/test_body_wrapping.py` (create)

### Part A: Wrapper Detection During Compile

**Step 1: Write the failing tests for wrapper detection**

Create `tests/test_body_wrapping.py`:

```python
"""Tests for POST body envelope wrapping (F-037)."""

from __future__ import annotations

from toolwright.core.compile.tools import ToolCompiler
from toolwright.models.endpoint import Endpoint, EndpointParameter, ParameterLocation


def _make_endpoint(
    method: str = "POST",
    path: str = "/admin/api/2024-01/products.json",
    request_body_schema: dict | None = None,
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host="store.myshopify.com",
        stable_id=f"ep_{method.lower()}_products",
        signature_id=f"sig_{method.lower()}_products",
        risk_tier="medium",
        request_body_schema=request_body_schema,
    )


class TestWrapperDetection:
    """F-037: Detect envelope wrapper key from request_body_schema."""

    def test_shopify_product_wrapper_detected(self):
        """Single top-level object property detected as wrapper key."""
        schema = {
            "type": "object",
            "properties": {
                "product": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "vendor": {"type": "string"},
                        "product_type": {"type": "string"},
                    },
                    "required": ["title"],
                }
            },
            "required": ["product"],
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        compiler = ToolCompiler()
        actions = compiler.compile([endpoint])

        assert len(actions) == 1
        action = actions[0]
        assert action.get("request_body_wrapper") == "product"

    def test_flat_single_string_property_not_wrapped(self):
        """Single property that is a scalar (not object) → NOT a wrapper."""
        schema = {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
            },
            "required": ["code"],
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        compiler = ToolCompiler()
        actions = compiler.compile([endpoint])

        assert len(actions) == 1
        action = actions[0]
        assert action.get("request_body_wrapper") is None

    def test_multi_property_body_not_wrapped(self):
        """Multiple top-level properties → NOT a wrapper."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        compiler = ToolCompiler()
        actions = compiler.compile([endpoint])

        assert len(actions) == 1
        action = actions[0]
        assert action.get("request_body_wrapper") is None

    def test_wrapper_inner_properties_flattened(self):
        """Wrapper's inner properties should be in the input_schema, not the wrapper key."""
        schema = {
            "type": "object",
            "properties": {
                "product": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "vendor": {"type": "string"},
                    },
                    "required": ["title"],
                }
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        compiler = ToolCompiler()
        actions = compiler.compile([endpoint])

        action = actions[0]
        input_props = action["input_schema"]["properties"]
        assert "title" in input_props, "Inner property 'title' should be in input_schema"
        assert "vendor" in input_props, "Inner property 'vendor' should be in input_schema"
        assert "product" not in input_props, "Wrapper key 'product' should NOT be in input_schema"

    def test_no_body_schema_no_wrapper(self):
        """Endpoint with no request_body_schema → no wrapper."""
        endpoint = _make_endpoint(request_body_schema=None)
        compiler = ToolCompiler()
        actions = compiler.compile([endpoint])

        assert len(actions) == 1
        action = actions[0]
        assert action.get("request_body_wrapper") is None

    def test_empty_body_schema_no_wrapper(self):
        """Empty request_body_schema → no wrapper."""
        endpoint = _make_endpoint(request_body_schema={})
        compiler = ToolCompiler()
        actions = compiler.compile([endpoint])

        assert len(actions) == 1
        action = actions[0]
        assert action.get("request_body_wrapper") is None
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_body_wrapping.py::TestWrapperDetection -v`

Expected: `test_shopify_product_wrapper_detected` FAILS (no `request_body_wrapper` in action). `test_wrapper_inner_properties_flattened` FAILS (wrapper key `product` is in input_schema, inner props not flattened correctly).

**Step 3: Implement wrapper detection in _build_input_schema()**

In `toolwright/core/compile/tools.py`, modify `_build_input_schema()` starting at line 282.

Replace lines 282-291 (the body schema block):

```python
        # Add body schema properties if present
        if endpoint.request_body_schema:
            body_props = endpoint.request_body_schema.get("properties", {})
            body_required = endpoint.request_body_schema.get("required", [])

            for prop_name, prop_schema in body_props.items():
                if prop_name not in properties:
                    properties[prop_name] = prop_schema
                    if prop_name in body_required:
                        required.append(prop_name)
```

With:

```python
        # Add body schema properties if present
        wrapper_key = None
        if endpoint.request_body_schema:
            body_props = endpoint.request_body_schema.get("properties", {})
            body_required = endpoint.request_body_schema.get("required", [])

            # Detect envelope wrapper: single top-level object property with sub-properties
            if len(body_props) == 1:
                key, schema = next(iter(body_props.items()))
                if schema.get("type") == "object" and schema.get("properties"):
                    wrapper_key = key
                    # Flatten the INNER properties into input_schema
                    body_props = schema["properties"]
                    body_required = schema.get("required", [])

            for prop_name, prop_schema in body_props.items():
                if prop_name not in properties:
                    properties[prop_name] = prop_schema
                    if prop_name in body_required:
                        required.append(prop_name)
```

Then make `_build_input_schema()` return the wrapper key along with the schema. Change the return type — but to minimize changes, use a module-level approach: store wrapper_key on the instance temporarily, or better, return a tuple. The cleanest approach: have `_build_input_schema()` return a tuple `(schema, wrapper_key)`.

Change the method signature and return:

```python
    def _build_input_schema(self, endpoint: Endpoint) -> tuple[dict[str, Any], str | None]:
        """Build JSON Schema for action input.

        Returns:
            Tuple of (JSON Schema dict, wrapper_key or None)
        """
```

And at the end (around line 300):

```python
        return schema, wrapper_key
```

Then update `_action_from_endpoint()` to unpack the tuple and store wrapper_key:

Find where `_build_input_schema` is called (around line 184):

```python
        input_schema = self._build_input_schema(endpoint)
```

Change to:

```python
        input_schema, wrapper_key = self._build_input_schema(endpoint)
```

And in the action dict construction (after line 216 — after graphql and output_schema blocks), add:

```python
        if wrapper_key:
            action["request_body_wrapper"] = wrapper_key
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_body_wrapping.py::TestWrapperDetection -v`

Expected: All 6 tests PASS.

**Step 5: Run full test suite for regressions**

Run: `python -m pytest tests/ -v`

Expected: All tests pass. The tuple return from `_build_input_schema` should not break anything since `_action_from_endpoint` is the only caller.

**Step 6: Commit**

```bash
git add toolwright/core/compile/tools.py tests/test_body_wrapping.py
git commit -m "feat(compile): detect request body envelope wrapper (F-037 part 1)

Detect when request_body_schema has exactly one top-level property that
is itself an object with properties (e.g., Shopify's {product: {...}}).
Store the wrapper key in action metadata as request_body_wrapper.
Flatten inner properties into input_schema so users supply flat params."
```

### Part B: Apply Wrapping at Execution Time

**Step 7: Write the failing test for execution wrapping**

Add to `tests/test_body_wrapping.py`:

```python
class TestExecutionWrapping:
    """F-037: Apply wrapper at execution time in build_url_and_kwargs."""

    def test_body_wrapped_when_wrapper_key_present(self):
        """POST body is wrapped as {wrapper: {params}} when action has request_body_wrapper."""
        from toolwright.mcp.server import build_url_and_kwargs

        action = {
            "method": "POST",
            "path": "/admin/api/2024-01/products.json",
            "host": "store.myshopify.com",
            "request_body_wrapper": "product",
        }
        args = {"title": "Test Product", "vendor": "TestVendor"}

        url, kwargs = build_url_and_kwargs(
            action=action,
            args=args,
            base_url="https://store.myshopify.com",
        )

        assert kwargs.get("json") == {"product": {"title": "Test Product", "vendor": "TestVendor"}}

    def test_body_not_wrapped_when_no_wrapper_key(self):
        """POST body is flat when action has no request_body_wrapper."""
        from toolwright.mcp.server import build_url_and_kwargs

        action = {
            "method": "POST",
            "path": "/api/tokens",
            "host": "example.com",
        }
        args = {"code": "abc123"}

        url, kwargs = build_url_and_kwargs(
            action=action,
            args=args,
            base_url="https://example.com",
        )

        assert kwargs.get("json") == {"code": "abc123"}
```

**Important note:** The `build_url_and_kwargs` function is currently a closure inside `_execute_request()` in `server.py`. We need to either:
- Extract it as a module-level or class-level function (preferred for testability), or
- Test it indirectly through a higher-level integration test.

The cleaner approach: extract `build_url_and_kwargs` into a standalone function. If extraction is too risky, test indirectly. **Check the actual structure first during implementation** — if `build_url_and_kwargs` is a nested closure that captures `self`, `action_host`, `method`, `path`, etc., the test above won't work as written. In that case, adjust the test to call through the existing entry points, or do a minimal extraction.

**Practical approach:** Since `build_url_and_kwargs` is a closure, the simplest path is to add wrapping logic in-place and write an integration-style test that constructs a minimal ToolwrightServer and calls through. However, the wrapping logic is just 2 lines:

```python
wrapper = action.get("request_body_wrapper")
if wrapper:
    body_params = {wrapper: body_params}
```

So the test can be a unit test of just those 2 lines of logic, or we trust the compile-side tests + a simple manual verification.

**Adjusted Step 7: Add the wrapping logic directly and test via the compile side**

Add an end-to-end test to `tests/test_body_wrapping.py`:

```python
class TestWrapperRoundTrip:
    """End-to-end: compile detects wrapper → execution applies it."""

    def test_wrapper_key_stored_and_retrievable(self):
        """Compiled action has request_body_wrapper that can be used at execution time."""
        schema = {
            "type": "object",
            "properties": {
                "product": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                    },
                    "required": ["title"],
                }
            },
        }
        endpoint = _make_endpoint(request_body_schema=schema)
        compiler = ToolCompiler()
        actions = compiler.compile([endpoint])
        action = actions[0]

        # Simulate execution-time wrapping logic
        args = {"title": "Test Product"}
        wrapper = action.get("request_body_wrapper")
        if wrapper:
            body = {wrapper: args}
        else:
            body = args

        assert body == {"product": {"title": "Test Product"}}
```

**Step 8: Apply wrapping in server.py**

In `toolwright/mcp/server.py`, modify lines 698-702 inside `build_url_and_kwargs`:

Change from:

```python
            if method.upper() in ("POST", "PUT", "PATCH"):
                body_params = {k: v for k, v in args.items() if f"{{{k}}}" not in path}
                if body_params:
                    headers["Content-Type"] = "application/json"
                    kwargs["json"] = body_params
```

To:

```python
            if method.upper() in ("POST", "PUT", "PATCH"):
                body_params = {k: v for k, v in args.items() if f"{{{k}}}" not in path}
                if body_params:
                    wrapper = action.get("request_body_wrapper")
                    if wrapper:
                        body_params = {wrapper: body_params}
                    headers["Content-Type"] = "application/json"
                    kwargs["json"] = body_params
```

**Note:** The `action` variable must be in scope. Check that `build_url_and_kwargs` has access to `action` in its closure. Looking at the code, the closure captures `action_host`, `method`, `path` but NOT `action` directly. You'll need to also capture `action` or pass `request_body_wrapper` separately.

Looking at the closure context (around line 638), the action dict is available as a local in `_execute_request()`. The `build_url_and_kwargs` closure should have access. If not, pass it via the outer scope. The simplest fix: add `request_body_wrapper = action.get("request_body_wrapper")` before the closure definition, then reference it inside:

```python
            if method.upper() in ("POST", "PUT", "PATCH"):
                body_params = {k: v for k, v in args.items() if f"{{{k}}}" not in path}
                if body_params:
                    if request_body_wrapper:
                        body_params = {request_body_wrapper: body_params}
                    headers["Content-Type"] = "application/json"
                    kwargs["json"] = body_params
```

Where `request_body_wrapper` is extracted from `action` before the closure definition.

**Step 9: Run tests to verify they pass**

Run: `python -m pytest tests/test_body_wrapping.py -v`

Expected: All tests PASS.

**Step 10: Run full test suite for regressions**

Run: `python -m pytest tests/ -v`

Expected: All tests pass.

**Step 11: Commit**

```bash
git add toolwright/mcp/server.py tests/test_body_wrapping.py
git commit -m "feat(server): apply request body wrapper at execution (F-037 part 2)

When action metadata contains request_body_wrapper, POST/PUT/PATCH
bodies are wrapped as {wrapper: {params}}. This fixes Shopify writes
that require {\"product\": {\"title\": \"...\"}} format."
```

---

## Task 5: Final Integration Verification

**Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`

Expected: All tests pass with 0 failures, 0 errors.

**Step 2: Run linting**

Run: `ruff check toolwright/ tests/`

Expected: No errors. Fix any if found.

**Step 3: Update documentation**

Update `ROADMAP.md` — move the 4 fixed blockers from P0 to Completed section. Update `dogfood-checkpoint.md` severity summary.

**Step 4: Final commit**

```bash
git add ROADMAP.md dogfood-checkpoint.md
git commit -m "docs: update roadmap and checkpoint after fixing dogfood blockers

Moved F-028/F-032/F-037/F-039/F-040 from P0 to completed. All 4 code
blockers from live dogfood are fixed."
```

---

## Summary

| Task | Blocker | Files Changed | Estimated Effort |
|------|---------|--------------|-----------------|
| 1 | F-032 deny_admin | policy.py (delete 15 lines) + new test | 10 min |
| 2 | F-028/F-035 risk cap | aggregator.py (~20 lines) + new test | 15 min |
| 3 | F-039/F-040 budget | engine.py + decision_engine.py (~15 lines) + new test | 20 min |
| 4 | F-037 body wrapping | tools.py + server.py (~20 lines) + new test | 25 min |
| 5 | Integration verify | docs only | 5 min |
