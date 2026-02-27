# README Funnel Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the README from a spec/reference document into a funnel that gets users to value in 90 seconds.

**Architecture:** Replace the current README (218 lines) with a funnel-structured version (same length) that leads with outcome promise, proof, guided quickstart (`toolwright ship`), tangible artifacts, and compact differentiators. Move reference tables to the bottom.

**Tech Stack:** Markdown, tui-studio for GIF generation

---

### Task 1: Write the new README

**Files:**
- Modify: `README.md`

**Step 1: Replace the entire README content**

Write the new README with this exact structure. The content below is the complete replacement:

```markdown
[![PyPI](https://img.shields.io/pypi/v/toolwright)](https://pypi.org/project/toolwright/)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/toolwright)](https://pypi.org/project/toolwright/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/toolwright/Toolwright/actions/workflows/ci.yaml/badge.svg)](https://github.com/toolwright/Toolwright/actions/workflows/ci.yaml)

# Toolwright — Fail-closed tools for AI agents

<!-- mcp-name: io.github.toolwright/toolwright -->

Turn any API into a governed MCP server in minutes. Approved tools are signed, enforced, and auditable.

<!-- hero-start -->
<p align="center">
  <img src="docs/assets/hero-comparison.gif" alt="Without Toolwright vs With Toolwright — side-by-side comparison" width="100%">
</p>

*Without Toolwright: agents silently gain new powers. With Toolwright: every tool is approved, signed, and enforced fail-closed.*

<!-- hero-end -->

## See It Work

```bash
pip install toolwright
toolwright demo
```

<p align="center">
  <img src="docs/assets/toolwright-demo.gif" alt="toolwright demo — governance proof in 30 seconds" width="80%">
</p>

Builds a governed toolpack from bundled traffic, proves fail-closed enforcement, and writes an auditable decision log. Exit `0` means every gate held.

## Quick Start

**Prerequisites:** Python 3.11+

```bash
toolwright init
toolwright ship
```

`toolwright ship` walks you through the full lifecycle interactively: capture, review, approve, snapshot, verify, serve. If you already have a toolpack, it detects it and skips ahead.

<p align="center">
  <img src="docs/assets/toolwright-ship.gif" alt="toolwright ship — guided lifecycle" width="80%">
</p>

### Other entry points

```bash
# Have an OpenAPI spec?
toolwright capture import openapi.yaml -a api.example.com

# Have HAR/OTEL traffic files?
toolwright capture import traffic.har -a api.example.com

# Then continue with:
toolwright ship
```

All paths converge to the same governed runtime.

## What You Get

Your agent calls `delete_user`:

```
DENIED — denied_not_approved
Tool "delete_user" is not in the approved lockfile.
Trace: 2026-02-22T14:30:01Z | tool_id=delete_user | reason=denied_not_approved
```

Your agent calls `list_users`:

```
ALLOWED — allowed_policy
Tool "list_users" approved, signed, policy evaluated.
Trace: 2026-02-22T14:30:02Z | tool_id=list_users | reason=allowed_policy
```

Every decision is logged. Every approval is Ed25519-signed. Unapproved tools never execute.

```
.toolwright/toolpacks/my-api/
├── toolpack.yaml       # metadata, display name, origin
├── tools.json          # compiled tool definitions with risk tiers
├── policy.yaml         # priority-ordered rules (allow, deny, confirm, budget)
├── baseline.json       # capability snapshot for drift detection
├── lockfile.yaml       # signed approval decisions per tool
└── contracts.yaml      # verification assertions (replay, provenance)
```

## Why Toolwright

- **Fail-closed** — no lockfile, no runtime. Unapproved tools never execute.
- **Signed approvals** — Ed25519 signatures on every lockfile entry.
- **Drift detection** — detect API surface changes against a baseline snapshot.
- **Self-repairing** — `toolwright repair` diagnoses issues and proposes classified fixes (safe, approval-required, manual).
- **Full audit trail** — every governance decision is logged with structured traces and evidence bundles.

## Drift Detection in CI

```yaml
# .github/workflows/toolwright-drift.yaml
name: API Drift Check
on:
  schedule:
    - cron: '0 6 * * 1'  # weekly on Monday
  workflow_dispatch:

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install toolwright
      - run: toolwright drift --toolpack .toolwright/toolpacks/*/toolpack.yaml --format markdown
```

## Claude Code / MCP Client Config

Generate a config snippet for your AI client:

```bash
toolwright config --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

Or add directly to Claude Desktop (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "my-api": {
      "command": "toolwright",
      "args": ["serve", "--toolpack", ".toolwright/toolpacks/my-api/toolpack.yaml"]
    }
  }
}
```

---

## Reference

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

### Traffic Capture

| You have | Command | Best for |
| --- | --- | --- |
| Nothing (exploring) | `toolwright demo` | Fastest first run, no credentials |
| A web app | `toolwright mint https://app.example.com -a api.example.com` | Capturing real behavior |
| HAR/OTEL files | `toolwright capture import traffic.har -a api.example.com` | Adopting without recapturing |
| An OpenAPI spec | `toolwright capture import openapi.yaml -a api.example.com` | Generating tools from specs |

### Runtime Enforcement

The MCP server enforces multiple safety layers on every tool call:

- **Lockfile approval** — only explicitly approved tools execute
- **Policy evaluation** — priority-ordered rules (allow, deny, confirm, budget, audit)
- **Rate limiting** — per-minute/per-hour budgets with sliding-window tracking
- **Network safety** — SSRF protection, metadata endpoint blocking, redirect validation
- **Confirmation flow** — HMAC-signed challenge tokens for sensitive operations
- **Redaction** — strips auth headers, tokens, PII from all captured data
- **Dry-run mode** — evaluate policy without executing upstream calls

### Installation

**Prerequisites:** Python 3.11+

```bash
# Base install (includes offline demo)
pip install toolwright

# With MCP server support
pip install "toolwright[mcp]"

# With live browser capture
pip install "toolwright[playwright]"
python -m playwright install chromium

# Everything
pip install "toolwright[all]"
```

## Documentation

- [User Guide](docs/user-guide.md) — full command reference and workflows
- [Architecture](docs/architecture.md) — system design and component specs
- [Glossary](docs/glossary.md) — key terms and concepts
- [Troubleshooting](docs/troubleshooting.md) — common issues and fixes
- [Known Limitations](docs/known-limitations.md) — runtime and capture caveats
- [Publishing](docs/publishing.md) — PyPI release process

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, TDD policy, and pull request process.

```bash
git clone https://github.com/toolwright/Toolwright.git
cd Toolwright
pip install -e ".[dev,packaging-test]"
pytest tests/ -v
```

## License

[MIT](LICENSE)
```

**Step 2: Verify the README renders correctly**

Run: `cd /Users/thomasallicino/oss/toolwright && wc -l README.md`
Expected: ~220 lines (similar to original)

Manually review for:
- No broken markdown syntax
- GIF paths reference existing files (hero-comparison.gif, toolwright-demo.gif)
- The toolwright-ship.gif reference is a placeholder (will be generated in Task 2)
- Command examples are accurate
- Reason codes match `toolwright/models/decision.py` (`denied_not_approved`, `allowed_policy`)

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: restructure README into a funnel

Lead with outcome promise, proof, and guided quickstart (toolwright ship).
Move reference tables to the bottom. Add 'What You Get' proof section
with DENIED/ALLOWED scenario and artifact tree.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Generate toolwright ship GIF

**Files:**
- Create: `docs/assets/toolwright-ship.gif`

**Step 1: Use tui-studio skill to generate the ship flow GIF**

The GIF should show the `toolwright ship` experience:
1. Stage tracker: `✓ capture ── >> review ── ○ approve ── ○ snapshot ── ○ verify ── ○ serve`
2. Tool preview (risk tier breakdown)
3. Approval flow (batch approve low-risk, individual review high-risk)
4. Progress through all stages
5. Final success message: "Ship Secure Agent complete!"

Use the tui-studio skill to create a deterministic demo that captures this flow.

Prompt identity should use `user` for username and basename-only path.

**Step 2: Verify the GIF file exists and is reasonably sized**

Run: `ls -lh docs/assets/toolwright-ship.gif`
Expected: File exists, size < 5MB

**Step 3: Commit**

```bash
git add docs/assets/toolwright-ship.gif
git commit -m "docs: add toolwright ship flow GIF for README quickstart

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Update user guide structure

**Files:**
- Modify: `docs/user-guide.md`

**Step 1: Restructure into narrative-first format**

Rewrite `docs/user-guide.md` with this outline:

1. **Getting Started** — install, `toolwright demo`, `toolwright init`
2. **Golden Path: Your First Governed API** — narrative walkthrough using `toolwright ship`
3. **Common Entry Points** — OpenAPI import, HAR import, live capture (with exact commands and expected output)
4. **Understanding Governance** — what fail-closed means, how approvals work, lockfile structure
5. **Day-2 Operations** — drift detection, repair, rename, audit log review
6. **CI Integration** — GitHub Actions for drift, verify in pipelines
7. **Full Command Reference** — existing content, preserved as reference

Keep all existing command documentation but reorganize so narrative comes first, reference comes last.

**Step 2: Verify no broken links**

Check that all internal links (`glossary.md`, `troubleshooting.md`, etc.) still work.

**Step 3: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs: restructure user guide — narrative first, reference last

Reorder to: getting started, golden path, entry points, governance model,
operations, CI, then full command reference.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Regenerate hero comparison GIF with new TUI experience

**Files:**
- Modify: `docs/assets/hero-comparison.gif`

**Step 1: Use tui-studio skill to regenerate the hero comparison GIF**

The GIF should show side-by-side:
- **Left (Without Toolwright):** Agent calls `delete_user` → silently succeeds, no audit, no control
- **Right (With Toolwright):** Agent calls `delete_user` → DENIED, audit logged, fail-closed

Use the latest TUI styling (arrow-key menus, display names, etc.).

Prompt identity: `user` for username, basename-only for path.

**Step 2: Verify file exists**

Run: `ls -lh docs/assets/hero-comparison.gif`

**Step 3: Commit**

```bash
git add docs/assets/hero-comparison.gif
git commit -m "docs: regenerate hero comparison GIF with current TUI

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Update CAPABILITIES.md

**Files:**
- Modify: `CAPABILITIES.md`

**Step 1: Add/update entries for new features**

Ensure CAPABILITIES.md includes:
- `CAP-UI-rename` — `toolwright rename` command
- `CAP-UI-display-name` — display name resolution in all UI surfaces
- Update any README references in capability entries

**Step 2: Commit**

```bash
git add CAPABILITIES.md
git commit -m "docs: update CAPABILITIES.md with display name and rename entries

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Final verification

**Step 1: Run lint on all changed Python files (if any)**

Run: `cd /Users/thomasallicino/oss/toolwright && .venv/bin/ruff check toolwright/ tests/`

**Step 2: Run full test suite**

Run: `cd /Users/thomasallicino/oss/toolwright && .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10`
Expected: All pass, 0 failures

**Step 3: Verify README renders**

Check that all GIF file references exist:

Run: `ls -la docs/assets/hero-comparison.gif docs/assets/toolwright-demo.gif docs/assets/toolwright-ship.gif`

**Step 4: Review README manually**

Read through the final README and verify:
- Funnel flow makes sense top-to-bottom
- No broken markdown
- Commands are accurate
- Reason codes match the codebase
- Artifact tree matches real toolpack structure
- GitHub Actions snippet is valid YAML
