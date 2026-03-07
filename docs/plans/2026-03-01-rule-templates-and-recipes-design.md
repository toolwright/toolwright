# Rule Templates + Recipe System Design

Date: 2026-03-01
Status: Approved

## Summary

Two features shipping as a single workstream:

1. **Rule templates** — reusable YAML files defining cross-cutting behavioral rules (crud-safety, rate-control, retry-safety). Applied via CLI or referenced by recipes.
2. **Recipes** — bundled YAML files for known APIs (GitHub, Shopify, Notion, Stripe, Slack). Pre-configure auth headers, extra headers, rule template references, and probe hints. Used via `mint --recipe <name>`.

These compound on each other: recipes reference templates, but templates work independently.

## Design Decisions

### Rule templates are the atomic unit, not recipes

Cross-cutting patterns (read-before-delete, rate-limit writes) are generic and composable. Embedding rules in recipes would duplicate them across recipe files and leave overlay users with no path to pre-built rules. Templates are independent; recipes reference them by name.

### `target_name_patterns` is primary, `target_methods` is convenience

`target_methods` depends on HTTP method metadata, which only exists for compiled tools. Overlay tools (e.g., `delete_row` from Supabase MCP) don't have HTTP methods. `target_name_patterns` uses glob matching against tool names and works everywhere.

Both fields are optional. `match` field controls union semantics:
- `match: all` (default) — tool must match ALL specified targeting fields (AND)
- `match: any` — tool matches if ANY targeting field hits (OR)

Templates use `match: any` for overlay-forward breadth. Hand-authored rules get `match: all` by default for intuitive intersection behavior.

### No risk_overrides in recipes

Risk classification belongs in the compiler. Per-recipe overrides would duplicate classifier logic and risk creating false safety (the same problem as the `/admin/` deny rule removed in F-032). If the compiler misclassifies an endpoint, that's a classifier bug to fix for everyone.

### Recipes reduce setup friction, not governance decisions

`mint --recipe` pre-fills hosts, auth headers, extra headers, and queues DRAFT rules. It does NOT: skip browser capture, auto-approve tools, activate rules, or download specs. The user still browses, reviews, and approves.

## Rule Template Format

Location: `toolwright/rules/templates/*.yaml`

```yaml
name: crud-safety
description: Require reading a resource before destructive operations
rules:
  - kind: prerequisite
    name: read-before-delete
    description: Require a read call before any destructive operation
    target_name_patterns: ["delete_*", "*_delete", "remove_*", "destroy_*"]
    target_methods: [DELETE]
    match: any
    config:
      required_tool_patterns: ["get_*", "list_*", "read_*", "fetch_*"]
    priority: 100

  - kind: prerequisite
    name: read-before-update
    description: Require a read call before any mutation
    target_name_patterns: ["update_*", "*_update", "edit_*", "modify_*"]
    target_methods: [PUT, PATCH]
    match: any
    config:
      required_tool_patterns: ["get_*", "list_*", "read_*", "fetch_*"]
    priority: 100

  - kind: approval
    name: confirm-destructive
    description: Require confirmation before destructive operations
    target_name_patterns: ["delete_*", "*_delete", "remove_*", "destroy_*"]
    target_methods: [DELETE]
    match: any
    config:
      approval_message: "This will permanently delete a resource. Confirm?"
    priority: 50
```

```yaml
name: rate-control
description: Rate limits on write operations and session budgets
rules:
  - kind: rate
    name: write-rate-limit
    description: Limit write operations to 10 per minute
    target_name_patterns: ["create_*", "update_*", "delete_*", "post_*", "put_*"]
    target_methods: [POST, PUT, PATCH, DELETE]
    match: any
    config:
      max_calls: 10
      window_seconds: 60
      per_tool: false
    priority: 100

  - kind: rate
    name: session-budget
    description: Cap total tool calls at 200 per session
    # window_seconds: null means entire session (no time window)
    config:
      max_calls: 200
      window_seconds: null
      per_tool: false
    priority: 200
```

```yaml
name: retry-safety
description: Prevent agents from retrying failed calls unproductively
rules:
  - kind: rate
    name: limit-consecutive-errors
    description: Rate limit any single tool to 3 calls per 30 seconds
    config:
      max_calls: 3
      window_seconds: 30
      per_tool: true
    priority: 100
```

## Schema Extensions

### BehavioralRule model (toolwright/models/rule.py)

New optional fields:

```python
target_name_patterns: list[str] = Field(default_factory=list)  # glob patterns via fnmatch
match: Literal["any", "all"] = "all"  # targeting field combination logic
```

### PrerequisiteConfig model

New optional field:

```python
required_tool_patterns: list[str] = Field(default_factory=list)  # glob patterns
```

### _applicable_rules() (toolwright/core/correct/engine.py)

Updated matching logic:

```
if match == "all":
    tool must match ALL non-empty targeting fields
    (target_tool_ids AND target_methods AND target_name_patterns AND target_hosts)
if match == "any":
    tool matches if ANY non-empty targeting field hits
    (target_tool_ids OR target_methods OR target_name_patterns OR target_hosts)
Empty fields are ignored (match-all). Existing behavior preserved when no patterns set.
```

### _evaluate_prerequisite()

Extended to check `required_tool_patterns` in addition to `required_tool_ids`:

```
For each pattern in required_tool_patterns:
    Check session history for any tool_id matching the glob pattern
    If no match found, violation
```

## Recipe Format

Location: `toolwright/recipes/*.yaml`

```yaml
name: shopify
description: Shopify Admin REST API
hosts:
  - pattern: "*.myshopify.com"
    auth_header_name: X-Shopify-Access-Token
    auth_scheme: api_key
extra_headers:
  Content-Type: application/json
setup_instructions_url: https://shopify.dev/docs/api/admin-rest
openapi_spec_url: null
rate_limit_hints: "2 req/sec at standard tier"
usage_notes: "All endpoints under /admin/api/{version}/."
rule_templates:
  - crud-safety
  - rate-control
probe_hints:
  expect_auth: true
  expect_openapi: false
```

### Per-host auth header name (runtime wiring)

`ToolpackAuthRequirement.header_name` already exists in the model. Runtime fix in server.py:

```python
def _resolve_auth_header_name(self, host: str) -> str:
    if self._auth_requirements:
        for req in self._auth_requirements:
            if req.host == host and req.header_name:
                return req.header_name
    return "Authorization"
```

### mint --recipe behavior

1. Load recipe YAML
2. Set `--allowed-hosts` from `hosts[*].pattern`
3. Set extra headers from `extra_headers`
4. Pass `probe_hints` to smart probe (skip unnecessary checks)
5. Run normal mint flow (probe → browser → compile)
6. Post-compile: populate `ToolpackAuthRequirement.header_name` from recipe hosts
7. Post-compile: load `rule_templates`, create DRAFT rules in `.toolwright/rules.json`
8. Print setup instructions including correct auth export commands

### CLI

```bash
toolwright recipes list                  # show available recipes
toolwright recipes show shopify          # print recipe details
toolwright mint --recipe shopify         # pre-fill config, run normal mint
```

## Initial Recipes

| Recipe | auth_header_name | extra_headers | rule_templates | openapi_spec_url |
|--------|-----------------|---------------|----------------|-----------------|
| github | Authorization (Bearer) | none | crud-safety | github REST API spec URL |
| shopify | X-Shopify-Access-Token | Content-Type: application/json | crud-safety, rate-control | null |
| notion | Authorization (Bearer) | Notion-Version: 2022-06-28 | crud-safety | null |
| stripe | Authorization (Bearer) | none | crud-safety, rate-control | null |
| slack | Authorization (Bearer) | none | rate-control | null |

## Deferred (backlog)

- `after_result_matches` + `cooldown_seconds` on ProhibitionConfig — for result-aware prohibition rules. Ship when rate limiting alone proves insufficient for a real user.
- Remote recipe fetching — if community demand exceeds what's bundled.
- Recipe auto-detection — `mint` probes could match against known recipes and suggest `--recipe`.

## Grounding

All rule templates are derived from real dogfood findings:

| Template | Finding | Observed behavior |
|----------|---------|-------------------|
| crud-safety | F-032 | Agent deleting resources without reading them first |
| rate-control | F-039/F-040 | Budget double-counting, uncontrolled write frequency |
| retry-safety | Shopify dogfood | Agent retrying scope-blocked (403) endpoints repeatedly |

Recipe auth_header_name motivated by F-055 (Shopify X-Shopify-Access-Token incompatible with Authorization header convention).
