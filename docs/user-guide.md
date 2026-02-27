# Cask User Guide

This guide walks you through governing your AI agent's tools with Cask. See the [Glossary](glossary.md) for definitions of key terms.

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
cask demo
```

Builds a governed toolpack from bundled traffic, proves fail-closed enforcement, and writes an auditable decision log. Exit `0` means every gate held.

### 2. Initialize your project

```bash
cask init
```

Creates the `.toolwright/` directory structure. Detects existing captures, OpenAPI specs, and auth configurations in your project.

### 3. Ship it

```bash
cask ship
```

Walks you through the full lifecycle interactively:

1. **Capture** — Detects existing toolpacks or prompts you to create one
2. **Review** — Shows a risk-tiered tool preview (critical/high/medium/low)
3. **Approve** — Gate review with approval counts by risk tier
4. **Snapshot** — Creates a baseline for drift detection
5. **Verify** — Runs verification contracts
6. **Serve** — Outputs the MCP server command

If any stage fails, `cask ship` tells you exactly what went wrong and what to do next.

### 4. Connect to your AI client

```bash
cask config --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

Generates a ready-to-paste config snippet for Claude Desktop, Cursor, or Codex.

---

## Common Entry Points

Different starting points all converge to the same governed runtime.

### You have a web app

```bash
cask mint https://app.example.com -a api.example.com
```

Opens a browser, records your API interactions, and compiles a governed toolpack in one shot. Then run `cask ship` to complete the lifecycle.

### You have an OpenAPI spec

```bash
cask capture import openapi.yaml -a api.example.com
cask ship
```

### You have HAR or OTEL files

```bash
# HAR files
cask capture import traffic.har -a api.example.com

# OpenTelemetry traces
cask capture import traces.json --input-format otel -a api.example.com
```

Then run `cask ship` to walk through the remaining stages.

### You have a live browser session

```bash
cask capture record https://app.example.com -a api.example.com
```

---

## Governance Model

### Fail-closed enforcement

No lockfile, no runtime. If a tool isn't explicitly approved in the signed lockfile, it never executes. There is no "allow by default" mode.

### Approval workflow

Every tool goes through a gate review:

```bash
# Approve all pending tools
cask gate allow --all

# Approve specific tools
cask gate allow get_users create_user

# Block a dangerous tool
cask gate block delete_all_users --reason "Too dangerous"

# Check approval status (CI-friendly)
cask gate check

# List current status
cask gate status
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
cask drift --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

For CI, use the `--format markdown` flag and wire it into your GitHub Actions (see README).

### Repair

When something breaks, `cask repair` diagnoses and proposes fixes:

```bash
cask repair --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

5-phase lifecycle: preflight → diagnosis → repair plan → guided resolution → re-verification. Fixes are classified as safe (auto-apply), approval-required, or manual.

### Verification

Run assertion-based contracts:

```bash
cask verify --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

Contracts check replay parity, provenance, and outcome consistency.

### Status

See governance health and recommended next action:

```bash
cask status --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

### Change reports

```bash
cask diff --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
cask diff --toolpack .toolwright/toolpacks/my-api/toolpack.yaml --format github-md
```

### Rename

```bash
cask rename "Stripe API" --toolpack .toolwright/toolpacks/stripe-api/toolpack.yaml
```

---

## MCP Server

### Start serving

```bash
cask serve --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
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
cask config --toolpack .toolwright/toolpacks/my-api/toolpack.yaml

# Codex TOML
cask config --toolpack .toolwright/toolpacks/my-api/toolpack.yaml --format codex
```

---

## Dashboard

Full-screen Textual dashboard for toolpack-scoped governance overview:

```bash
pip install "toolwright[tui]"
cask dashboard --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

Falls back to `cask status` output when Textual is not installed.

---

## Command Reference

### Core Commands

| Command | What it does |
| --- | --- |
| `cask` | Interactive guided menu (run with no arguments) |
| `cask ship` | Guided end-to-end lifecycle: capture, review, approve, verify, serve |
| `cask status` | Show governance status and recommended next action |
| `cask init` | Initialize Cask in your project |
| `cask mint <url>` | Capture traffic and compile a governed toolpack |
| `cask gate allow\|block\|check\|status` | Approve, block, or audit tools via signed lockfile |
| `cask serve` | Start the governed MCP server (stdio) |
| `cask diff` | Generate a risk-classified change report |
| `cask drift` | Detect API surface changes against a baseline |
| `cask verify` | Run verification contracts (replay, outcomes, provenance) |
| `cask repair` | Diagnose issues and propose classified fixes |
| `cask rename` | Rename a toolpack's display name |
| `cask propose` | Manage agent draft proposals for new capabilities |
| `cask inspect` | Start read-only Meta MCP for agent introspection |
| `cask config` | Generate MCP client config (Claude Desktop, Codex) |
| `cask dashboard` | Full-screen Textual dashboard (`toolwright[tui]`) |
| `cask demo` | Prove governance works (offline, 30 seconds) |

> Use `cask --help-all` to see all 25+ commands including `compliance`, `bundle`, `enforce`, `confirm`, and more.

### Verification Workflows

```bash
cask workflow init              # Initialize a workflow
cask workflow run workflow.yaml # Run a workflow
cask workflow diff run_a/ run_b/  # Compare two runs
cask workflow report run_dir/   # Generate a report
cask workflow doctor            # Check dependencies
```

### Help

- `cask --help` shows the core command surface.
- `cask --help-all` shows all commands including advanced ones.

---

## Troubleshooting

See [Troubleshooting](troubleshooting.md) for common issues and fixes.

## Known Limitations

See [Known Limitations](known-limitations.md) for runtime and capture caveats.
