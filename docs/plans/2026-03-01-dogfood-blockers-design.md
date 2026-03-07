# Design: Fix Dogfood Blockers

> **Date:** 2026-03-01
> **Scope:** 4 Toolwright code blockers from live dogfood (F-028/F-032/F-037/F-039/F-040)
> **APIs affected:** Shopify Admin REST (and any API with `/admin/` prefixes, envelope-style bodies, or confirmation flows)

---

## Blocker 1: Risk Classification for Template Hosts (F-028/F-035)

### Problem
`CRITICAL_PATH_KEYWORDS` regex matches `admin` in Shopify paths like `/admin/api/2024-01/products.json`. Every Shopify tool is classified `critical`, cascading to: all tools require confirmation, `--max-risk` filtering unusable. 1181/1183 Shopify tools affected.

### Root Cause
`_determine_risk_tier()` in `aggregator.py:615-647` applies `CRITICAL_PATH_KEYWORDS` to all methods equally. A `GET /admin/api/products.json` (safe read) gets the same `critical` classification as `DELETE /admin/api/products/{id}.json` (destructive write).

### Fix: Method-aware risk capping
**Rule:** If method is `GET`, `HEAD`, or `OPTIONS`, cap the risk tier at `medium` — never higher, regardless of path keywords.

**Important edge cases:**
- `DELETE /admin/api/products/{id}.json` → keywords still match → `critical` (unchanged)
- `POST /admin/api/products.json` → keywords still match → `critical` (unchanged)
- `GET /admin/api/products.json` → keywords would match `critical`, but capped to `medium`
- `GET /admin/api/payments/refunds.json` → keywords would match `critical`, but capped to `medium`

**Implementation:** The keyword matching runs for ALL methods. The cap applies AFTER classification:

```python
def _determine_risk_tier(self, method, path, is_auth_related, has_pii, is_first_party):
    # Existing logic runs unchanged for all methods
    tier = self._classify_tier(method, path, is_auth_related, has_pii, is_first_party)

    # Cap: read-only methods never exceed medium
    if method.upper() in ("GET", "HEAD", "OPTIONS") and RISK_ORDER.get(tier, 0) > RISK_ORDER["medium"]:
        tier = "medium"

    return tier
```

### Files Changed
- `toolwright/core/normalize/aggregator.py` — `_determine_risk_tier()` (~5 lines added)

### Tests
- New: GET with `/admin/` path → `medium` (not `critical`)
- New: DELETE with `/admin/` path → `critical` (unchanged)
- New: POST with `/admin/` path → `critical` (unchanged)
- New: GET with `/payments/` path → `medium` (capped)
- Existing: all current risk tests must still pass

---

## Blocker 2: Remove deny_admin Policy Rule (F-032)

### Problem
Auto-generated `deny_admin` rule in `policy.py:178-193` matches `.*/admin.*` at priority 200. Fires before any allow rule, blocks ALL Shopify endpoints. Redundant with risk classification + confirmation gates + behavioral rules.

### Root Cause
The `deny_admin` rule is a relic from before risk classification was trusted. Now that we have risk tiers, confirmation gates, and behavioral rules, it's pure redundancy causing harm.

### Fix: Delete the deny_admin rule generation
Remove the 15 lines that generate this rule. If anyone later needs to block admin paths, they add a behavioral rule explicitly.

### Files Changed
- `toolwright/core/compile/policy.py` — delete lines 178-193 (deny_admin generation block)
- `tests/` — update any tests that assert deny_admin exists in generated policy

### Tests
- New: generated policy for Shopify-like spec has NO deny_admin rule
- New: `GET /admin/api/products.json` evaluates to ALLOW (not DENY) through generated policy
- Existing: all other generated rules (allow_first_party_get, confirm_state_changes, etc.) still generated

---

## Blocker 3: POST Body Envelope Wrapping (F-037)

### Problem
Shopify requires `{"product": {"title": "..."}}` but Toolwright sends `{"title": "..."}`. The compile phase flattens `request_body_schema` into `input_schema`, losing the wrapper key. At execution time, no metadata exists to reconstruct the envelope.

### Root Cause Chain
1. **Compile** (`tools.py:_build_input_schema()`): Flattens body properties into top-level input_schema
2. **Action metadata** (`tools.py:_action_from_endpoint()`): Doesn't include `request_body_schema` or wrapper info
3. **Execute** (`server.py:build_url_and_kwargs()`): Sends flat `body_params` as-is

### Fix: Detect wrapper key during compile, store in action, wrap at execution

**Detection heuristic** (during compile):
If `request_body_schema` has exactly one top-level property AND that property's type is `object` with its own `properties`, treat it as a wrapper key.

```python
# In _build_input_schema():
wrapper_key = None
if endpoint.request_body_schema:
    props = endpoint.request_body_schema.get("properties", {})
    if len(props) == 1:
        key, schema = next(iter(props.items()))
        # Only treat as wrapper if the single property is an object with sub-properties
        if schema.get("type") == "object" and schema.get("properties"):
            wrapper_key = key
            # Flatten the INNER properties into input_schema
            body_props = schema["properties"]
            body_required = schema.get("required", [])
```

**Why the heuristic is safe:**
- `{"product": {"title": "...", "vendor": "..."}}` → single prop `product` is object with properties → wrapper ✓
- `{"code": "abc123"}` → single prop `code` is string, not object → NOT a wrapper ✓
- `{"name": "...", "email": "..."}` → multiple top-level props → NOT a wrapper ✓

**Storage:** Add `request_body_wrapper: str | None` to action metadata dict.

**Execution** (`server.py:build_url_and_kwargs()`):
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

### Files Changed
- `toolwright/core/compile/tools.py` — `_build_input_schema()` (wrapper detection) + `_action_from_endpoint()` (store wrapper key)
- `toolwright/mcp/server.py` — `build_url_and_kwargs()` (apply wrapping at execution)

### Tests
- New: Shopify-like spec with `{"product": {"title": ...}}` → wrapper detected as `"product"`
- New: Flat body `{"code": "abc123"}` → no wrapper detected
- New: Multi-property body → no wrapper detected
- New: Execution with wrapper → body is `{"product": {"title": "...", ...}}`
- New: Execution without wrapper → body is `{"title": "...", ...}` (unchanged)

---

## Blocker 4: Budget/Rate-Limit Double-Counting (F-039/F-040)

### Problem
Confirmation flow calls `pipeline.execute()` twice: once for challenge creation, once for token redemption. Budget consumed both times (2 units per confirmed call). Session rate limits checked against stale history.

### Root Cause
`PolicyEngine.evaluate()` calls `BudgetTracker.consume()` on every evaluation, regardless of whether the decision is ALLOW (actual execution) or CONFIRM (challenge creation). The engine doesn't know the difference.

### Fix: Add `dry_run` flag to skip budget consumption during challenge creation

**Flow after fix:**

```
Request 1 (challenge creation):
  pipeline.execute() → decision_engine.evaluate()
    → policy_engine.evaluate(dry_run=True)   ← CHECK budget but DON'T consume
    → requires_step_up=True → return CONFIRM
  (0 budget consumed, 0 session entries)

Request 2 (token redemption):
  pipeline.execute() → decision_engine.evaluate()
    → policy_engine.evaluate(dry_run=False)  ← CHECK AND CONSUME budget
    → token consumed → return ALLOW
  → _execute_and_process() → session.record()
  (1 budget consumed, 1 session entry)
```

**Implementation:**

1. **PolicyEngine.evaluate()** gets `dry_run: bool = False` parameter:
```python
def evaluate(self, method, path, host, risk_tier, scope, *, dry_run=False):
    # ... existing matching logic ...
    elif rule.type == RuleType.BUDGET:
        tracker = self._budgets.get(rule.id)
        if tracker:
            if not tracker.check():
                budget_exceeded = True
            elif not dry_run:        # <-- Only consume when NOT dry_run
                tracker.consume()
```

2. **DecisionEngine.evaluate()** does a two-pass evaluation when confirmation is needed:
```python
def evaluate(self, request, context):
    # First pass: evaluate policy (consuming budget)
    policy_result = policy_engine.evaluate(..., dry_run=False)

    # If we need step-up AND no token provided → this was a challenge request
    if requires_step_up and not request.confirmation_token_id:
        # Roll back: re-check without consuming
        # Actually simpler: just don't consume in the first place
        ...
```

Actually, cleaner approach — the decision engine can predict whether it needs a challenge BEFORE calling policy:

```python
def evaluate(self, request, context):
    # Determine if this will be a challenge (no token + requires confirmation)
    is_challenge_path = (
        request.mode == "execute"
        and not request.confirmation_token_id
        and self._will_require_step_up(request, context)
    )

    policy_result = policy_engine.evaluate(
        ..., dry_run=is_challenge_path
    )
```

OR even simpler — consume budget only when we know the final decision is ALLOW:

```python
def evaluate(self, request, context):
    policy_result = policy_engine.evaluate(..., dry_run=True)  # Always dry_run first

    # ... all decision logic ...

    if final_decision == DecisionType.ALLOW:
        policy_engine.consume_budget(...)  # Consume only on ALLOW

    return result
```

**Simplest correct approach:** Always evaluate policy in dry_run mode, then explicitly consume after the full decision is computed and equals ALLOW.

### Files Changed
- `toolwright/core/enforce/engine.py` — `PolicyEngine.evaluate()` gets `dry_run` param; add `consume_budget()` method
- `toolwright/core/enforce/decision_engine.py` — call `evaluate(dry_run=True)`, then `consume_budget()` only on ALLOW

### Tests
- New: confirmed call consumes 1 budget unit (not 2)
- New: `max_calls=3` allows 3 confirmed calls (not 1-2)
- New: challenge creation (CONFIRM result) consumes 0 budget
- New: direct ALLOW still consumes 1 budget (no regression)
- Existing: all budget and rate limit tests still pass

---

## Implementation Order

1. **Blocker 2 (deny_admin)** — Simplest, pure deletion. Unblocks Shopify policy immediately.
2. **Blocker 1 (risk classification)** — Small change, unblocks `--max-risk` and confirmation gates.
3. **Blocker 4 (budget double-counting)** — Medium complexity, fixes confirmation flow.
4. **Blocker 3 (POST body wrapping)** — Most complex, fixes write operations.

Each blocker is independent — they can be implemented and tested in isolation.
