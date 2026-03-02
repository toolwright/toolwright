# Toolwright User Guide

Toolwright is the immune system for AI agent tools -- it monitors your tools in production, heals them when APIs change, circuit-breaks them when they fail, and enforces behavioral rules that agents learn from. This guide walks you through the full lifecycle. See the [Glossary](glossary.md) for definitions of key terms.

## Install

```bash
pip install toolwright
```

Optional extras:

```bash
# MCP server support
pip install "toolwright[mcp]"

# Live browser capture
pip install "toolwright[playwright]"
python -m playwright install chromium

# Full-screen TUI dashboard
pip install "toolwright[tui]"

# Everything
pip install "toolwright[all]"
```

For source/development workflows:

```bash
pip install -e ".[dev]"
```

**New to Toolwright?** Start with a quickstart:
- [GitHub API in 5 minutes](quickstarts/github.md)
- [Any REST API](quickstarts/any-rest-api.md)

---

## Golden Path

The fastest way to go from zero to a governed MCP server:

### 1. See it work (30 seconds)

```bash
toolwright demo
```

Builds a governed toolpack from bundled traffic, proves fail-closed enforcement, and writes an auditable decision log. Exit `0` means every gate held.

### 2. Build your tools

```bash
toolwright ship
```

Walks you through the full lifecycle interactively:

1. **Capture** — Detects existing toolpacks or prompts you to create one
2. **Review** — Shows a risk-tiered tool preview (critical/high/medium/low)
3. **Approve** — Gate review with approval counts by risk tier
4. **Snapshot** — Creates a baseline for drift detection
5. **Verify** — Runs verification contracts
6. **Serve** — Outputs the MCP server command

If any stage fails, `toolwright ship` tells you exactly what went wrong and what to do next.

### 3. Connect to your AI client

```bash
toolwright config
```

Generates a ready-to-paste config snippet for Claude Desktop, Cursor, or Codex.

> **Auto-resolution:** When your project has a single toolpack, `--toolpack` is optional on all commands. See [Toolpack Resolution](#toolpack-resolution) below.

### Fine-grained control

For power users who want to run each stage individually:

```bash
toolwright init                     # set up project
toolwright mint <url> -a <host>     # capture + compile
toolwright diff                     # review risk-classified changes
toolwright gate allow --all         # approve tools
toolwright verify                   # run verification contracts
toolwright serve                    # start MCP server
toolwright drift                    # detect API changes (CI/cron)
```

---

## Toolpack Resolution

Toolwright automatically resolves which toolpack to use. The resolution chain:

1. `--toolpack` flag (explicit, always wins)
2. `TOOLWRIGHT_TOOLPACK` env var
3. `.toolwright/config.yaml` -> `default_toolpack` setting
4. Auto-detect: if exactly one toolpack exists, use it
5. Error with actionable message listing available toolpacks

### Setting a Default

When you have multiple toolpacks:

```bash
toolwright use stripe        # set default to the 'stripe' toolpack
toolwright use github        # switch default to 'github'
toolwright use --clear       # remove the default setting
```

This writes to `.toolwright/config.yaml`:

```yaml
default_toolpack: stripe
```

## Auth Check

Verify your auth configuration is correct before serving:

```bash
toolwright auth check
```

This checks each host in the toolpack's `allowed_hosts` and:
- Shows whether per-host and global env vars are set
- Probes each host with a lightweight GET to verify the token works
- Suggests the exact `export` command if auth is missing

```bash
# Skip probing (offline/CI environments)
toolwright auth check --no-probe
```

---

## Common Entry Points

Different starting points all converge to the same governed runtime.

### You have a web app

```bash
toolwright mint https://app.example.com -a api.example.com
```

Opens a browser, records your API interactions, and compiles a governed toolpack in one shot. Then run `toolwright ship` to complete the lifecycle.

### You have an OpenAPI spec

```bash
toolwright capture import openapi.yaml -a api.example.com
toolwright ship
```

### You have HAR or OTEL files

```bash
# HAR files
toolwright capture import traffic.har -a api.example.com

# OpenTelemetry traces
toolwright capture import traces.json --input-format otel -a api.example.com
```

Then run `toolwright ship` to walk through the remaining stages.

### You have a live browser session

```bash
toolwright capture record https://app.example.com -a api.example.com
```

---

## Governance Model

### Fail-closed enforcement

No lockfile, no runtime. If a tool isn't explicitly approved in the signed lockfile, it never executes. There is no "allow by default" mode.

### Approval workflow

Every tool goes through a gate review. All gate commands auto-resolve the toolpack (or accept `--toolpack` for explicit override):

```bash
# Approve all pending tools
toolwright gate allow --all
# Approve specific tools
toolwright gate allow get_users create_user
# Block a dangerous tool
toolwright gate block delete_all_users --reason "Too dangerous"
# Check approval status (CI-friendly)
toolwright gate check
# List current status
toolwright gate status
```

### Signed approvals

Every lockfile entry is Ed25519-signed. The signature chain is: tool definition → risk classification → approval decision → lockfile entry. Tampering breaks the chain and triggers a verification failure.

### Risk tiers

Tools are automatically classified into risk tiers based on HTTP method, path patterns, and payload analysis:

- **Critical** — Destructive operations (DELETE, admin endpoints)
- **High** — Write operations (POST, PUT, PATCH)
- **Medium** — Read operations with sensitive data
- **Low** — Read-only operations

### Policy engine

Priority-ordered rules control runtime behavior:

```yaml
# Example policy.yaml
rules:
  - match: { tool: "delete_*" }
    action: deny
    reason: "Destructive operations blocked"
  - match: { tool: "list_*" }
    action: allow
  - match: { risk: "critical" }
    action: confirm
```

Actions: `allow`, `deny`, `confirm` (requires out-of-band token grant via `toolwright confirm grant`), `budget` (rate-limited), `audit` (log-only).

---

## Operations

### Drift detection

Detect API surface changes between your baseline and current state:

```bash
toolwright drift
```

For CI, use the `--format markdown` flag and wire it into your GitHub Actions (see README).

### Repair

When something breaks, `toolwright repair` diagnoses and proposes fixes:

```bash
toolwright repair
```

5-phase lifecycle: preflight → diagnosis → repair plan → guided resolution → re-verification. Fixes are classified as safe (auto-apply), approval-required, or manual.

### Verification

Run assertion-based contracts:

```bash
toolwright verify
```

Contracts check replay parity, provenance, and outcome consistency.

### Status

See governance health and recommended next action:

```bash
toolwright status
```

### Change reports

```bash
toolwright diff --format github-md
```

### Rename

```bash
toolwright rename "Stripe API"
```

---

## Authentication

### Environment variable (recommended)

Set auth via environment variable to avoid tokens in shell history:

```bash
export TOOLWRIGHT_AUTH_HEADER="Bearer your-token-here"
toolwright serve
```

### Per-host auth

For toolpacks covering multiple APIs, set per-host env vars:

```bash
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer github-token"
export TOOLWRIGHT_AUTH_API_STRIPE_COM="Bearer stripe-token"
toolwright serve
```

Per-host naming: replace dots and hyphens with underscores, uppercase everything. `api.github.com` becomes `TOOLWRIGHT_AUTH_API_GITHUB_COM`.

### CLI flag

For quick testing, pass auth directly:

```bash
toolwright serve --auth "Bearer your-token"
```

**Priority order:** `--auth` flag > `TOOLWRIGHT_AUTH_<HOST>` env var > `TOOLWRIGHT_AUTH_HEADER` env var.

---

## Behavioral Rules (CORRECT Pillar)

Define persistent behavioral constraints that agents must follow across sessions. Six rule types cover common safety patterns.

### Rule types

| Kind | Purpose | Example |
|------|---------|---------|
| `prerequisite` | Require tool A before tool B | Must `get_repo` before `patch_repo_issue` |
| `prohibition` | Block a tool entirely | Never call `delete_repo_contents` |
| `parameter` | Restrict parameter values | Label color must match `^[0-9a-fA-F]{6}$` |
| `rate` | Limit calls per session | Max 5 `post_repo_issue` calls |
| `sequence` | Enforce call ordering | Must follow A → B → C |
| `approval` | Require explicit confirmation | Approve before `create_deployment` |

### Creating rules

```bash
# Require reading repo before modifying issues
toolwright rules add --kind prerequisite \
  --target patch_repo_issue \
  --requires get_repo \
  --description "Must read repo context before modifying issues"

# Block dangerous operations
toolwright rules add --kind prohibition \
  --target delete_repo_contents \
  --description "Never delete repository files"

# Rate limit API calls
toolwright rules add --kind rate \
  --target post_repo_issue \
  --max-calls 5 \
  --description "Max 5 new issues per session"

# Restrict parameter values
toolwright rules add --kind parameter \
  --target post_repo_label \
  --param-name color \
  --pattern "^[0-9a-fA-F]{6}$" \
  --description "Label color must be valid hex"
```

### Managing rules

```bash
# List all rules
toolwright rules list

# Filter by kind
toolwright rules list --kind prohibition

# Show rule details
toolwright rules show <rule_id>

# Remove a rule
toolwright rules remove <rule_id>

# Export/import for portability
toolwright rules export --output rules-backup.json
toolwright rules import --input rules-backup.json
```

### Rule Templates

Toolwright ships with bundled rule templates for common governance patterns:

- **crud-safety** — Require reading a resource before deleting or updating it
- **rate-control** — Limit write operations (10/min) and total calls (200/session)
- **retry-safety** — Prevent unproductive retry loops (3 calls/30s per tool)

#### Browsing templates

```bash
toolwright rules template list
toolwright rules template show crud-safety
```

#### Applying templates

```bash
toolwright rules template apply crud-safety
```

Templates create DRAFT rules by default. Review and activate:

```bash
toolwright rules drafts
toolwright rules activate <rule-id>
```

Or apply and activate in one step:

```bash
toolwright rules template apply crud-safety --activate
```

### Serving with rules

```bash
toolwright serve --toolpack toolpack.yaml --rules-path .toolwright/rules.json
```

When an agent violates a rule, Toolwright returns structured feedback explaining what went wrong and how to fix it.

---

## API Recipes

Recipes pre-fill mint settings for known APIs:

```bash
toolwright recipes list
toolwright recipes show shopify
toolwright mint --recipe shopify https://yourstore.myshopify.com
```

Bundled recipes: github, shopify, notion, stripe, slack.

Each recipe sets: hosts, auth headers, extra headers, and rule template references. Post-mint, referenced templates are queued as DRAFT rules.

---

## Circuit Breakers (KILL Pillar)

Per-tool circuit breakers protect your agent from cascading API failures. They automatically trip after repeated failures and recover after a timeout.

### Three-state model

- **CLOSED** (normal) — tool calls pass through. Trips OPEN after 5 consecutive failures.
- **OPEN** (blocked) — all tool calls blocked. Auto-transitions to HALF_OPEN after 60s timeout.
- **HALF_OPEN** (probing) — allows one probe call. Resets to CLOSED after 3 successes, or back to OPEN on failure.

### Manual kill/enable

```bash
# Kill a tool immediately (e.g., API returning 500s)
toolwright kill search_api --reason "Upstream 500s"

# Check what's quarantined
toolwright quarantine

# Check a specific breaker
toolwright breaker-status search_api

# Re-enable when the API recovers
toolwright enable search_api
```

Manually killed tools **never auto-recover** — they require explicit `toolwright enable`.

### Serving with circuit breakers

```bash
toolwright serve --toolpack toolpack.yaml \
  --circuit-breaker-path .toolwright/state/circuit_breakers.json
```

---

## Continuous Reconciliation (HEAL Pillar)

Toolwright uses Kubernetes-style reconciliation for recovery of its own artifacts and runtime, and Terraform-style plan/apply for changes to what tools do.

Start the MCP server with `--watch` and Toolwright continuously monitors your tools for API drift, schema changes, and endpoint failures. When issues are detected, repairs are classified and handled automatically or queued for your review.

### Watch mode

```bash
toolwright serve --watch --auto-heal safe
```

Three auto-heal levels:

- `off` — detect drift and failures, but never auto-apply repairs
- `safe` — auto-apply patches classified as SAFE (e.g., new optional response fields)
- `all` — auto-apply SAFE and APPROVAL_REQUIRED patches (use with caution)

Probe intervals are configured per risk tier:

| Risk tier | Default interval |
|-----------|-----------------|
| Critical | 120s |
| High | 300s |
| Medium | 600s |
| Low | 1800s |

### Checking status

```bash
# Per-tool health overview
toolwright watch status

# Filtered event log
toolwright watch log --tool search_api --last 10
```

### Repair workflow

When drift or failures are detected, use the Terraform-style repair workflow:

```bash
# See what changed and what needs fixing
toolwright repair plan

# Apply classified repairs
toolwright repair apply
```

Repairs are classified by patch safety:

- **SAFE** (green) — auto-apply without review (e.g., new optional fields)
- **APPROVAL_REQUIRED** (yellow) — needs human approval (e.g., path changes)
- **MANUAL** (red) — requires investigation (e.g., endpoint removed)

> Patch safety classifies how a repair can be applied. Not to be confused with risk tiers (low/medium/high/critical), which classify tools.

### Snapshots and rollback

Every auto-repair is preceded by a snapshot. If something goes wrong, restore the exact previous state:

```bash
# List available snapshots
toolwright snapshots

# Restore a previous state
toolwright rollback <snapshot-id>
```

Pruning keeps a maximum of 20 snapshots and protects those referenced by pending repairs or active repair plans.

### Watch configuration

Override defaults in `.toolwright/watch.yaml`:

```yaml
auto_heal: safe
intervals:
  critical: 120
  high: 300
  medium: 600
  low: 1800
```

---

## MCP Server

### Start serving

```bash
toolwright serve
```

### Serve-time scoping

Control what tools are exposed and how they behave:

```bash
# Serve only tools in specific groups (auto-generated from URL paths)
toolwright serve --scope products,orders

# Prefix matching: 'repos' includes repos, repos/issues, repos/pulls
toolwright serve --scope repos

# Only expose tools in a named toolset (defined during compilation)
toolwright serve --toolset readonly

# Cap the maximum risk tier of exposed tools
toolwright serve --max-risk low       # low | medium | high | critical

# Inject custom headers into every upstream request
toolwright serve -H "Notion-Version: 2025-09-03"
toolwright serve --extra-header "X-Custom: value"

# Control output schema strictness
toolwright serve --schema-validation warn   # strict | warn | off
```

**`--scope`** filters by auto-generated tool groups. Groups are created during compile from URL path structure (e.g., `/products` endpoints become the `products` group). Use prefix matching to include sub-groups: `--scope repos` serves `repos`, `repos/issues`, and `repos/pulls`. Multiple groups: `--scope products,orders`. See available groups with `toolwright groups list`.

**Tool count guardrails** warn when serving 31-200 tools, and block above 200 (override with `--no-tool-limit`). Use `--scope` to narrow large APIs to agent-friendly subsets.

**`--toolset`** filters tools by named sets (e.g., `readonly`, `admin`). Only tools in the specified set are listed.

**`--max-risk`** caps the risk tier. `--max-risk low` hides all medium/high/critical tools.

**`--extra-header` / `-H`** injects headers into every upstream request. Useful for APIs requiring version headers (Notion, Shopify) or custom identifiers. Can be specified multiple times. Does not override the `Authorization` header set via auth env vars.

**`--schema-validation`** controls whether the server advertises `outputSchema` to MCP clients:
- `strict` — advertise output schemas. Clients validate responses against them.
- `warn` (default) — don't advertise output schemas. Avoids client-side validation errors from imprecise community specs.
- `off` — don't advertise output schemas. Same behavior as `warn`.

The server enforces multiple safety layers on every tool call:

- **Lockfile approval** — only explicitly approved tools execute
- **Policy evaluation** — priority-ordered rules (allow, deny, confirm, budget, audit)
- **Rate limiting** — per-minute/per-hour budgets with sliding-window tracking
- **Network safety** — SSRF protection, metadata endpoint blocking, redirect validation
- **Confirmation flow** — single-use tokens for sensitive operations (`toolwright confirm grant`)
- **Redaction** — strips auth headers, tokens, PII from all captured data
- **Dry-run mode** — evaluate policy without executing upstream calls

### Client config

```bash
# JSON (Claude Desktop, Cursor)
toolwright config
# Codex TOML
toolwright config --format codex
```

---

## Dashboard

### Web Dashboard

When serving over HTTP, Toolwright includes a built-in web dashboard at the server root:

```bash
toolwright serve --http
# Dashboard: http://localhost:8745/?t=tw_...
```

The dashboard provides:

- **Hero cards** — tool count, health %, uptime
- **Tools table** — name, method, path, risk tier
- **Live event feed** — SSE-powered real-time events (tool calls, decisions, drift, breaker trips)

Auth: the token is passed via URL query parameter on first load, then stripped from the browser URL bar.

### TUI Dashboard

Full-screen Textual dashboard for toolpack-scoped governance overview:

```bash
pip install "toolwright[tui]"
toolwright dashboard
```

Falls back to `toolwright status` output when Textual is not installed.

---

## Command Reference

### Core Commands

| Command | What it does |
| --- | --- |
| `toolwright` | Interactive guided menu (run with no arguments) |
| `toolwright ship` | Guided end-to-end lifecycle: capture, review, approve, verify, serve |
| `toolwright status` | Show governance status and recommended next action |
| `toolwright init` | Initialize Toolwright in your project |
| `toolwright mint <url>` | Capture traffic and compile a governed toolpack |
| `toolwright gate allow\|block\|check\|status` | Approve, block, or audit tools via signed lockfile |
| `toolwright serve` | Start the governed MCP server (stdio or `--http`) |
| `toolwright diff` | Generate a risk-classified change report |
| `toolwright drift` | Detect API surface changes against a baseline |
| `toolwright verify` | Run verification contracts (replay, outcomes, provenance) |
| `toolwright repair` | Diagnose issues and propose classified fixes |
| `toolwright rename` | Rename a toolpack's display name |
| `toolwright propose` | Manage agent draft proposals for new capabilities |
| `toolwright groups list` | List auto-generated tool groups with counts |
| `toolwright groups show <name>` | Show tools in a specific group |
| `toolwright recipes list` | List bundled API recipes |
| `toolwright recipes show <name>` | Show recipe details |
| `toolwright rules template list` | List bundled rule templates |
| `toolwright rules template apply <name>` | Create DRAFT rules from a template |
| `toolwright inspect` | Start read-only Meta MCP for agent introspection |
| `toolwright config` | Generate MCP client config (Claude Desktop, Codex) |
| `toolwright dashboard` | Full-screen Textual dashboard (`toolwright[tui]`) |
| `toolwright demo` | Prove governance works (offline, 30 seconds) |

> Use `toolwright --help-all` to see all 35+ commands including `compliance`, `bundle`, `enforce`, `confirm`, and more.

### Help

- `toolwright --help` shows the core command surface.
- `toolwright --help-all` shows all commands including advanced ones.

---

## Troubleshooting

See [Troubleshooting](troubleshooting.md) for common issues and fixes.

## Known Limitations

See [Known Limitations](known-limitations.md) for runtime and capture caveats.
