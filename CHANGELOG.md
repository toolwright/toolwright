# Changelog

All notable changes to Toolwright are documented here.

## [1.0.0a2] - 2026-03-09

### Added

**CONNECT Pillar**
- `toolwright wrap` command — govern any existing MCP server as a transparent overlay
- Smart pre-flight API probing during `toolwright mint` with structured output
- Request body envelope wrapper detection and automatic execution-time application
- `--scope` and `--no-tool-limit` options for `toolwright serve` with tool count guardrails
- Tool group data model, grouping algorithm, and compile pipeline integration

**GOVERN Pillar**
- Bundled API recipes with loader and CLI (`toolwright recipes`)
- Rule template loader with per-host authentication and `--recipe` wiring

**CORRECT Pillar**
- Glob-based rule targeting via `target_name_patterns` and `match` field
- `required_tool_patterns` for glob-based prerequisite enforcement

### Fixed
- Budget consumed only on final ALLOW decision, not intermediate checks
- Read-only HTTP methods capped at medium risk classification
- Removed incorrect `deny_admin` rule auto-generation from policy engine

### Changed
- Rewrote README for clarity, conversion, and concision
- Added MIT LICENSE file
- Added PyPI trusted publisher CI workflow
- Cleaned internal specs and working files from version control

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
- Workflow runner (Tide integration)
- Status and health monitoring
- Demo and onboarding flow
