# Known Limitations

## Capture and discovery

- Capture depth is best for common search/list/detail flows; highly custom UI flows may require scripted capture or manual HAR import.
- Headless capture may be blocked by anti-bot protections (Cloudflare, Akamai, etc.). Workarounds: use `--no-headless` for interactive capture, `--load-storage-state` with pre-authenticated sessions, or import HAR files from manual browser sessions.
- Single page loads may miss endpoints that require user interaction. Use scripted capture (`--script`) to exercise specific flows.
- Abstraction quality still improves with sample diversity. Toolwright can generalize obvious long slug-style `.json` listing routes from a single sample, but 2+ representative entities are still recommended for ambiguous/non-file route patterns.

## GraphQL

- GraphQL splitting is best-effort: when captured request bodies include `operationName`, Toolwright emits one tool per observed operation. If `operationName` is missing (for example anonymous/persisted-query-only traffic), calls still merge into a generic GraphQL tool.
- Operation-specific GraphQL tools are constrained by fixed `operationName`, and operation type (`query` vs `mutation`) is inferred from captured query text with operation-name heuristics as fallback. When confidence is low, behavior stays conservative.
- When query text is unique per operation, operation-specific tools fix `query`/`extensions` in the tool `fixed_body` so operators only provide `variables` (avoid copy/paste of large GraphQL payloads).
- **Single-endpoint GraphQL APIs** — APIs like Linear are GraphQL-only (single POST to `/graphql`). Minting from this produces one tool for the entire API, which is too coarse for meaningful governance. REST alternatives exist for some APIs (Shopify REST Admin, GitHub REST API), but Linear and others are GraphQL-only. GraphQL introspection support — generating virtual tools per query/mutation — is on the roadmap at P1.

## Auth and SSO

- Guided interactive reauth is required for MFA/passkeys/device-trust flows.
- `storageState` reuse may fail on some apps; persistent context fallback exists for difficult cases.
- **Per-request dynamic auth** — APIs requiring per-request cryptographic signing are not supported. Toolwright's auth model injects static headers (Bearer tokens, API keys); it cannot generate per-request signatures that are functions of the request method, path, body, and timestamp. Affected APIs include Coinbase Advanced Trade (EC private key → per-endpoint JWT), AWS services (SigV4), and any HMAC-SHA256 request-signing API. This affects a small slice of the API market — most SaaS APIs (Stripe, Shopify, Notion, GitHub, Slack, etc.) use standard Bearer tokens or API keys that Toolwright handles natively. An auth plugin/hook system is on the roadmap at P3.

## Telemetry noise

- Modern sites fire many analytics/telemetry requests (events, traces, beacons) that are legitimate first-party XHR calls. These pass the host filter and appear as tools. They are correctly captured but may not be useful for agent tools. Consider filtering specific paths after capture.

## OpenTelemetry input

- OTEL support is currently import-only from exported files (JSON/NDJSON). Live OTLP collector ingestion is not implemented yet.
- Span coverage depends on your instrumentation and sampling; missing HTTP attributes reduce extraction quality.
- Request/response bodies are often absent in OTEL spans for privacy/performance reasons, so generated schemas may be less complete than HAR/Playwright captures.

## Path normalization

- Comma-separated ID lists in path segments (e.g., `/products/ID1,ID2,ID3,...`) are not normalized. Each unique combination becomes a separate endpoint.
- Short UUID formats (e.g., `abc123-def4`) that don't match RFC 4122 may not be normalized to `{uuid}`.

## Proposal compiler

- `propose from-capture` currently ships a conservative resolver set (for example Next.js build IDs and CSRF token hints). Additional resolver plugins may be needed for site-specific ephemeral parameters.
- Next.js `/_next/data/{buildId}/...` routes are supported via a runtime resolver: tools mark the build ID parameter as derived and it is auto-resolved by parsing `__NEXT_DATA__` from HTML. This can still fail on hostile sites that return challenge pages instead of normal HTML.
- Endpoint-catalog confidence and follow-up questions are heuristic-scored from observed traffic; they are intended to guide operator review, not replace it.
- `propose publish` applies explicit confidence/risk gates by default (`--min-confidence 0.75`, `--max-risk high`). On sparse captures, operators may need to lower thresholds or gather additional examples before publication.

## Provenance

- Non-HTTP driven UI updates (cache/service worker/websocket/local-only state) may return `unknown` instead of `pass`.
- Provenance scoring is deterministic heuristic ranking, not a formal proof of causality.

## Runtime

- `mcp inspect` is read-only and not intended for runtime mutation workflows.
- `--unsafe-no-lockfile` bypass exists for local debugging only and is intentionally noisy.
- Some hostile/anti-bot sites (Cloudflare/Akamai protected) will return challenge pages or `403` when executed from a non-browser HTTP runtime. In these cases Toolwright is still valuable for capture/compilation/governance/verification, but live execution should be treated as best-effort unless you run requests via a browser-mediated runtime with explicit operator control.
- On macOS, GUI apps may be restricted from accessing `~/Documents`, `~/Desktop`, and `~/Downloads` unless explicitly granted permission. If your MCP client spawns `toolwright` from one of these locations, you may see `PermissionError: [Errno 1] Operation not permitted ... pyvenv.cfg`. Prefer installing `toolwright` and storing toolpacks outside those folders for Claude Desktop integration.

## Tool groups

- Groups are auto-generated from URL path structure. There is no built-in `groups edit` command yet; to customize group assignments, edit `groups.json` by hand after compile.
- The path cleaning algorithm strips common noise segments (`api`, `admin`, `rest`, version prefixes) but may not cover all API-specific conventions. Custom noise patterns are not configurable.
- Auto-split threshold (80 tools) and max depth (3) are hardcoded constants, not user-configurable.

## HTTP transport authentication

- The HTTP transport (`--use-http`) uses self-generated bearer tokens (`tw_` prefix, 128-bit hex) for MCP endpoint authentication. Tokens are per-session by default (auto-generated at startup) or set via `TOOLWRIGHT_TOKEN` env var. This is sufficient for local and single-user deployments.
- Tokens are not scoped (no per-tool or per-client permissions), not rotatable without restart, and not integrated with external identity providers. Enterprise environments that require OAuth 2.1, SAML/SSO, or RBAC-scoped tokens will need an auth proxy in front of Toolwright's HTTP endpoint.
- The June 2025 MCP spec classifies MCP servers as OAuth Resource Servers and mandates RFC 8707 Resource Indicators. Toolwright's `tw_` tokens are simpler than this spec requirement. Compliance with the MCP OAuth flow is a known gap for enterprise adoption.

## Security boundaries

- Toolwright does not claim bypass capability for anti-bot controls, MFA, or hostile sites.
- Toolwright does not claim legal certification; it provides technical controls and evidence for audit readiness.
