# Roadmap

Engineering backlog. Items prioritized by user impact.

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
  not shown in CLI status output

## Strategic expansion (designed, not yet scheduled)

- **Governance Overlay** — Wrap any existing MCP server with Toolwright's
  behavioral rules, circuit breakers, and approval workflow. Transforms
  Toolwright from API compiler to behavioral safety layer for all MCP tools.
  No breaking changes required, pipeline executor seam already exists.

## P0 (blocking users)

- **API recipes** — Community-contributable YAML files containing pointers (not
  bundled specs) for popular APIs. Each recipe has: base URL, auth header name/pattern, extra
  headers needed, setup instructions URL, link to community OpenAPI spec, rate limit hints, and
  usage notes. Start with 5-10 popular APIs.

## P1 (high friction)

- **Support per-host auth header names** — `TOOLWRIGHT_AUTH_*` always maps to
  `Authorization` header, incompatible with APIs using custom auth headers (Shopify:
  `X-Shopify-Access-Token`, Notion: `Notion-Version`). Need per-host header name config
  or detect from OpenAPI `securitySchemes`.

- **Pass auth to health probes** — Health probes send HEAD/OPTIONS without auth headers.
  Authenticated GET endpoints report AUTH_EXPIRED. Need to pass extra-headers to
  HealthChecker for accurate health assessment.

- **Fix HAR capture quality** — HAR-compiled tools have 0 input params, `? ?`
  method/path, all `critical` risk, and unredacted auth tokens. Fix: coerce str→Path in
  parse_file(), extract method/path from HAR entries, infer params from query strings.

- **Fix RepairEngine auto-repair** — RepairEngine detects integrity tampering but
  proposes 0 patches (diagnostic-only). Generate actual patches for common drift patterns.

- **GraphQL virtual tools via introspection** — APIs like Linear are GraphQL-only (single POST
  to `/graphql`). One endpoint = one tool = too coarse for governance. Approach: send
  introspection query, parse schema, generate one virtual tool per query/mutation.

## Completed

- **Fix risk classification for read-only methods** — GET/HEAD/OPTIONS methods are
  now capped at `medium` risk regardless of path keywords.

- **Fix policy generation for `/admin/` patterns** — Removed auto-generated `deny_admin`
  rule from policy compiler.

- **Fix budget/rate-limit double-counting on confirmed calls** — PolicyEngine now
  supports `dry_run` evaluation. Confirmed calls consume exactly 1 unit.

- **Fix POST body envelope wrapping** — Compile-time detection of single top-level object
  property as envelope wrapper. Inner properties flattened into input schema.

- **Output schema strictness levels** — `--schema-validation [strict|warn|off]` flag
  on `toolwright serve`. Default `warn` suppresses `outputSchema` and `structuredContent`.

- **Auth env var startup warning** — `toolwright serve` warns at startup when expected
  auth env vars are not set. Prints the exact `export` command.

- **Query params in OpenAPI import** — OpenAPI query parameters now flow through the full
  pipeline: parser → synthetic URL → normalizer → endpoint params → tool input properties.

- **Smart mint feedback (probe logic)** — Pre-flight probe runs before every `mint` command.
  Probes each host for: auth requirements, Content-Type, OpenAPI spec, GraphQL introspection.

## P2 (quality-of-life)

- **Auth setup friction** — Add `.env` file support in the toolpack directory and
  `toolwright auth set <host>` interactive prompt that writes tokens to toolpack `.env`.

- **`groups list` default view** — With 169 groups for GitHub, the full list is too long.
  Default to top 10 groups by tool count with `groups list --all` for full listing.

## P3 (build when demand proves it)

- **Per-request dynamic auth** — Some APIs require per-request cryptographic signing
  (Coinbase, AWS SigV4, HMAC-SHA256). Incompatible with static-header injection.
  Future: auth plugin/hook system. Don't build until real user demand proves it.

- **Configurable circuit breaker threshold** — Current 4 consecutive failures may be too high.
  Consider making configurable per risk tier.

- **Improve probe efficiency** — Probe cycle efficiency ~50% of theoretical maximum.
  Consider concurrent probing or adaptive tick intervals.
