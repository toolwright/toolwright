# Toolwright User Guide

This guide walks you through governing your AI agent's tools with Toolwright. See the [Glossary](glossary.md) for definitions of key terms.

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

---

## Golden Path

The fastest way to go from zero to a governed MCP server:

### 1. Prove it works (30 seconds)

```bash
toolwright demo
```

Builds a governed toolpack from bundled traffic, proves fail-closed enforcement, and writes an auditable decision log. Exit `0` means every gate held.

### 2. Initialize your project

```bash
toolwright init
```

Creates the `.toolwright/` directory structure. Detects existing captures, OpenAPI specs, and auth configurations in your project.

### 3. Ship it

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

### 4. Connect to your AI client

```bash
toolwright config --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

Generates a ready-to-paste config snippet for Claude Desktop, Cursor, or Codex.

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

Every tool goes through a gate review. All gate commands accept `--toolpack` for unified path resolution:

```bash
# Approve all pending tools
toolwright gate allow --all --toolpack .toolwright/toolpacks/my-api/toolpack.yaml

# Approve specific tools
toolwright gate allow get_users create_user --toolpack .toolwright/toolpacks/my-api/toolpack.yaml

# Block a dangerous tool
toolwright gate block delete_all_users --reason "Too dangerous" --toolpack .toolwright/toolpacks/my-api/toolpack.yaml

# Check approval status (CI-friendly)
toolwright gate check --toolpack .toolwright/toolpacks/my-api/toolpack.yaml

# List current status
toolwright gate status --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
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

Actions: `allow`, `deny`, `confirm` (requires HMAC challenge), `budget` (rate-limited), `audit` (log-only).

---

## Operations

### Drift detection

Detect API surface changes between your baseline and current state:

```bash
toolwright drift --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

For CI, use the `--format markdown` flag and wire it into your GitHub Actions (see README).

### Repair

When something breaks, `toolwright repair` diagnoses and proposes fixes:

```bash
toolwright repair --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

5-phase lifecycle: preflight → diagnosis → repair plan → guided resolution → re-verification. Fixes are classified as safe (auto-apply), approval-required, or manual.

### Verification

Run assertion-based contracts:

```bash
toolwright verify --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

Contracts check replay parity, provenance, and outcome consistency.

### Status

See governance health and recommended next action:

```bash
toolwright status --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

### Change reports

```bash
toolwright diff --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
toolwright diff --toolpack .toolwright/toolpacks/my-api/toolpack.yaml --format github-md
```

### Rename

```bash
toolwright rename "Stripe API" --toolpack .toolwright/toolpacks/stripe-api/toolpack.yaml
```

---

## Authentication

### Environment variable (recommended)

Set auth via environment variable to avoid tokens in shell history:

```bash
export TOOLWRIGHT_AUTH_HEADER="Bearer your-token-here"
toolwright serve --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

### Per-host auth

For toolpacks covering multiple APIs, set per-host env vars:

```bash
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer github-token"
export TOOLWRIGHT_AUTH_API_STRIPE_COM="Bearer stripe-token"
toolwright serve --toolpack .toolwright/toolpacks/multi-api/toolpack.yaml
```

Per-host naming: replace dots and hyphens with underscores, uppercase everything. `api.github.com` becomes `TOOLWRIGHT_AUTH_API_GITHUB_COM`.

### CLI flag

For quick testing, pass auth directly:

```bash
toolwright serve --toolpack .toolwright/toolpacks/my-api/toolpack.yaml --auth "Bearer your-token"
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

### Serving with rules

```bash
toolwright serve --toolpack toolpack.yaml --rules-path .toolwright/rules.json
```

When an agent violates a rule, Toolwright returns structured feedback explaining what went wrong and how to fix it.

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

## MCP Server

### Start serving

```bash
toolwright serve --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

The server enforces multiple safety layers on every tool call:

- **Lockfile approval** — only explicitly approved tools execute
- **Policy evaluation** — priority-ordered rules (allow, deny, confirm, budget, audit)
- **Rate limiting** — per-minute/per-hour budgets with sliding-window tracking
- **Network safety** — SSRF protection, metadata endpoint blocking, redirect validation
- **Confirmation flow** — HMAC-signed challenge tokens for sensitive operations
- **Redaction** — strips auth headers, tokens, PII from all captured data
- **Dry-run mode** — evaluate policy without executing upstream calls

### Client config

```bash
# JSON (Claude Desktop, Cursor)
toolwright config --toolpack .toolwright/toolpacks/my-api/toolpack.yaml

# Codex TOML
toolwright config --toolpack .toolwright/toolpacks/my-api/toolpack.yaml --format codex
```

---

## Dashboard

Full-screen Textual dashboard for toolpack-scoped governance overview:

```bash
pip install "toolwright[tui]"
toolwright dashboard --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
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
| `toolwright serve` | Start the governed MCP server (stdio) |
| `toolwright diff` | Generate a risk-classified change report |
| `toolwright drift` | Detect API surface changes against a baseline |
| `toolwright verify` | Run verification contracts (replay, outcomes, provenance) |
| `toolwright repair` | Diagnose issues and propose classified fixes |
| `toolwright rename` | Rename a toolpack's display name |
| `toolwright propose` | Manage agent draft proposals for new capabilities |
| `toolwright inspect` | Start read-only Meta MCP for agent introspection |
| `toolwright config` | Generate MCP client config (Claude Desktop, Codex) |
| `toolwright dashboard` | Full-screen Textual dashboard (`toolwright[tui]`) |
| `toolwright demo` | Prove governance works (offline, 30 seconds) |

> Use `toolwright --help-all` to see all 25+ commands including `compliance`, `bundle`, `enforce`, `confirm`, and more.

### Verification Workflows

```bash
toolwright workflow init              # Initialize a workflow
toolwright workflow run workflow.yaml # Run a workflow
toolwright workflow diff run_a/ run_b/  # Compare two runs
toolwright workflow report run_dir/   # Generate a report
toolwright workflow doctor            # Check dependencies
```

### Help

- `toolwright --help` shows the core command surface.
- `toolwright --help-all` shows all commands including advanced ones.

---

## Troubleshooting

See [Troubleshooting](troubleshooting.md) for common issues and fixes.

## Known Limitations

See [Known Limitations](known-limitations.md) for runtime and capture caveats.
