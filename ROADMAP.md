# Roadmap

Post-dogfood engineering backlog. Items prioritized based on live dogfood findings (83 findings across GitHub + Shopify).

## Deferred from hardening (known gaps)

- **Hash-chained audit log** — P3, append-only tamper evidence for audit trail
- **Real Windows CI** — Platform guards are in place but unverified without a Windows runner

## From architecture review feedback

- **Flapping detection** — Per-tool ring buffer of recent repair fingerprints. If same tool
  repaired >3 times in 30 minutes, escalate to APPROVAL_REQUIRED and log flapping warning
- **Explicit escalation state machine** — Unify repair classification + circuit breaker into
  single per-tool state: HEALTHY → AUTO_HEALING → NEEDS_APPROVAL → MANUAL → QUARANTINED
- **Automation budget** — If total drift events across all tools exceed threshold in time
  window, ratchet auto-heal down globally and require approvals
- **Canary validation** — Run contract verification against patched toolpack before promoting
  to active runtime (verify-then-promote, not traffic splitting)
- **Post-apply auto-rollback** — If post-apply probe fails, auto-restore from pre-patch
  snapshot and escalate to APPROVAL_REQUIRED
- **MAPE-K documentation** — Document reconciliation as Monitor/Analyze/Plan/Execute/Knowledge
  loop in architecture docs
- **Surface suspended tools in `watch status`** — `repair_suspended` is tracked internally but
  not shown in CLI status output. Operators only see the WARNING log during `serve --watch`.

## P0 (blocking users — from dogfood)

- **Smart mint feedback (probe logic)** — When `mint` is pointed at a URL, probe first and
  respond intelligently instead of silently doing the wrong thing. Send unauthenticated GET to
  base URL, inspect 401/403 for auth pattern hints (Bearer, API key, custom header), try POST
  to `<base>/graphql` with introspection query to detect GraphQL, check common spec paths
  (`/openapi.json`, `/swagger.json`). ~50-100 lines of probe logic. Estimated effort: 2-3 days.

- **API recipes (post-dogfood)** — Community-contributable YAML files containing pointers (not
  bundled specs) for popular APIs. Each recipe has: base URL, auth header name/pattern, extra
  headers needed, setup instructions URL, link to community OpenAPI spec, rate limit hints, and
  usage notes. Example: Notion recipe specifies `Authorization: Bearer` + `Notion-Version` header
  + link to community spec. Recipes are ~15 lines of YAML each, change maybe once a year,
  trivially reviewable via PR. Usage: `toolwright recipes list`, `toolwright recipes show notion`,
  `toolwright mint --recipe notion`. Start with 5-10 popular APIs (Shopify, Notion, GitHub,
  Stripe, Slack). Estimated effort: 2-3 days for the recipe system.

## P1 (high friction — from dogfood)

- **Support per-host auth header names (F-055)** — `TOOLWRIGHT_AUTH_*` always maps to
  `Authorization` header, incompatible with APIs using custom auth headers (Shopify:
  `X-Shopify-Access-Token`, Notion: `Notion-Version`). Options: per-host header name env var
  (`TOOLWRIGHT_AUTH_HEADER_NAME_<HOST>=X-Shopify-Access-Token`), toolpack auth header name
  config, or detect from OpenAPI `securitySchemes`.

- **Pass auth to health probes (F-048)** — Health probes send HEAD/OPTIONS without auth headers.
  All authenticated GET endpoints report AUTH_EXPIRED. Probes verify reachability, not
  authorization. Need to pass extra-headers to HealthChecker for accurate health assessment.

- **Fix HAR capture quality (F-063-F-068)** — HAR-compiled tools have 0 input params, `? ?`
  method/path, all `critical` risk, and unredacted auth tokens. Fix: coerce str→Path in
  parse_file(), extract method/path from HAR entries, infer params from query strings, redact
  auth tokens in captured data.

- **Fix RepairEngine auto-repair (F-045, F-046)** — RepairEngine detects integrity tampering but
  proposes 0 patches (diagnostic-only). Init requires 3 objects instead of a path. Generate
  actual patches for common drift patterns.

- **GraphQL virtual tools via introspection** — APIs like Linear are GraphQL-only (single POST
  to `/graphql`). Auth is fine (static Bearer token), but one endpoint = one tool = too coarse
  for governance. Approach: send introspection query, parse schema, generate one virtual tool per
  query/mutation. Estimated effort: 2-3 weeks.

## Completed (from dogfood)

- **Fix risk classification for read-only methods (F-028, F-035)** — GET/HEAD/OPTIONS methods are
  now capped at `medium` risk regardless of path keywords. Write methods keep full classification.
  Shopify GET tools no longer classified `critical` due to `/admin/` in paths.

- **Fix policy generation for `/admin/` patterns (F-032)** — Removed auto-generated `deny_admin`
  rule from policy compiler. Shopify endpoints (all under `/admin/`) are no longer blanket-denied.

- **Fix budget/rate-limit double-counting on confirmed calls (F-039, F-040)** — PolicyEngine now
  supports `dry_run` evaluation. DecisionEngine evaluates without consuming budget, then explicitly
  calls `consume_budget()` only on final ALLOW. Confirmed calls consume exactly 1 unit.

- **Fix POST body envelope wrapping (F-037)** — Compile-time detection of single top-level object
  property as envelope wrapper (e.g. Shopify `{"product": {...}}`). Inner properties are flattened
  into input schema. Wrapper key stored in action metadata and applied at execution time.

- **Output schema strictness levels (F-018)** — `--schema-validation [strict|warn|off]` flag
  on `toolwright serve`. Default `warn` suppresses `outputSchema` and `structuredContent` to avoid
  client-side validation errors from imprecise community specs. Verified against GitHub (1048 tools)
  and Shopify (1183 tools).

- **Auth env var startup warning (F-017)** — `toolwright serve` warns at startup when expected
  auth env vars (per-host `TOOLWRIGHT_AUTH_<HOST>`) are not set. Prints the exact `export` command.

- **Query params in OpenAPI import (F-019)** — OpenAPI query parameters now flow through the full
  pipeline: parser → synthetic URL → normalizer → endpoint params → tool input properties.
  Verified: 101/1079 GitHub endpoints gained query params (201 new input properties total).

## P3 (build only when real user demand proves it)

- **Per-request dynamic auth (auth plugin/hook system)** — Some APIs require per-request
  cryptographic signing where the Authorization header is a function of (timestamp + method +
  path + body + secret). Affected APIs: Coinbase Advanced Trade (EC private key → per-endpoint
  JWT), AWS services (SigV4), any HMAC-SHA256 request-signing API. Fundamentally incompatible
  with Toolwright's static-header injection model. Future approach: auth plugin/hook system where
  users register a signing function. Don't build until real user demand proves it — affected API
  surface is tiny compared to the static-auth market (most SaaS APIs use Bearer tokens or API
  keys that Toolwright handles natively).

- **Lower circuit breaker threshold (F-077)** — 4 consecutive unhealthy probes don't trip the
  circuit breaker. Threshold may be too high for environments wanting fast detection. Consider
  making configurable per risk tier.

- **Improve probe efficiency (F-076)** — Probe cycle efficiency ~50% of theoretical maximum due
  to batch network latency dominating cycle time. Consider concurrent probing or adaptive tick
  intervals based on actual probe duration.
