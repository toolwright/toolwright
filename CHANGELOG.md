# Changelog

All notable changes to Toolwright are documented here.

## [Unreleased]

## [1.0.0a3] - 2026-03-14

### Added

**Transport-Agnostic Governance**
- GovernanceRuntime: transport-neutral factory for wiring all governance subsystems
- CLI transport adapter: JSONL protocol on stdin/stdout (`toolwright serve --transport cli`)
- Transport conformance test suite ensuring identical governance across MCP + CLI
- `--transport` option for `toolwright serve` (stdio, http, cli)

**New Commands**
- `toolwright score`: governance maturity grading (A-F) with actionable suggestions
- `toolwright why <tool>`: explain governance decisions for any tool
- `toolwright estimate-tokens`: token cost comparison across transports
- Auth setup wizard: interactive credential setup for toolpack auth requirements

**Launch Materials**
- Show HN post and first comment draft (`docs/launch/show-hn.md`)
- Twitter/X launch thread (`docs/launch/twitter-thread.md`)

### Changed
- ToolwrightMCPServer refactored to delegate to GovernanceRuntime (~300 lines removed)
- GovernanceEngine parameterized with transport_type for transport-aware audit traces
- `toolwright wrap` connection lifecycle hardened (timeout, retry, clean errors)
- README rewritten for transport-agnostic positioning ("Any transport. Same governance.")
- Architecture docs updated for transport-agnostic governance
- PyPI keywords updated for discoverability (cli, governance, lockfile, security)
- CI workflow added (`.github/workflows/ci.yml`)

### Fixed
- 33 UX issues fixed across CLI (error messages, help text, exit codes)
- Auth setup: `.env` file now loaded before checking credentials (was silently skipping)
- Dotenv save: secrets written atomically with 0600 permissions (no TOCTOU window)
- Score command: `status` variable hoisted to prevent UnboundLocalError
- CLI transport: removed dead `asyncio.get_event_loop()` call
- Bare toolpack name resolution extended to all CLI commands
- OpenAPI parser handles 3.1 type arrays
- Ed25519 signature verification enforced in gate check and serve

## [1.0.0a2] - 2026-03-09

### Changed

- Replaced obsolete legacy proof references with Toolwright-native `demo` / `demo --smoke` readiness flows.
- Added real release-gate work toward build, test, lint, type-check, and installed-wheel smoke validation.
- Aligned public onboarding and publishing docs with the current PyPI-first alpha surface.
- Tightened source-distribution hygiene to avoid shipping local operational artifacts.

## [1.0.0a1] - 2026-02-26

### Added

**CONNECT Pillar**
- Multi-source API capture (HAR, OpenAPI, OTEL, browser, WebMCP)
- Tool manifest compilation with automatic risk classification
- Authentication detection (Bearer, OAuth, API keys)
- One-command API onboarding (`toolwright mint`)
- MCP server provisioning (`toolwright serve`)
- Toolset scoping for access control
- MCP client config generation (`toolwright config`)
- Project initialization wizard (`toolwright init`)
- OAuth2 client-credentials provider with automatic token refresh

**GOVERN Pillar**
- Ed25519 cryptographic approval signing
- Lockfile-based approval workflow (`toolwright gate`)
- Policy-based enforcement (allow/deny/confirm/budget/audit/redact)
- Runtime decision engine with reason codes
- Structured audit logging
- Network safety controls (SSRF prevention)
- Integrity verification (SHA256 digests)
- Approval snapshots and re-seal
- Confirmation gate with single-use tokens

**HEAL Pillar**
- Drift detection between API captures
- Repair engine with diagnosis and patch generation
- Interactive repair flow
- Verification and evidence bundles
- Contract-based testing
- Endpoint health checker with failure classification
- Automated proposal generation

**KILL Pillar**
- Fail-closed enforcement (default deny)
- Circuit breaker state machine (CLOSED/OPEN/HALF_OPEN)
- Manual kill and enable switches
- Quarantine reporting
- Circuit breaker MCP integration
- Response size limits
- Timeout enforcement
- Dry-run mode

**CORRECT Pillar**
- Behavioral rule engine (6 rule types)
- Session history tracking
- Rule conflict detection
- Violation feedback generation
- MCP server rule enforcement
- Rules CLI management

**Meta MCP Server**
- GOVERN introspection tools (7 tools)
- HEAL diagnosis tools (2 tools)
- KILL circuit breaker tools (3 tools)
- CORRECT behavioral rule tools (3 tools)

**Cross-Cutting**
- Rich terminal UI (TUI)
- Status and health monitoring
- Demo and onboarding flow
