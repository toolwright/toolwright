# README Funnel Redesign — Design Document

**Date:** 2026-02-22
**Goal:** Restructure the README from a spec/reference document into a funnel that gets users to value in 90 seconds.

**Core insight:** The product is solid. The packaging tells users "here's a system to learn" instead of "in 2 minutes you'll have a governed MCP server that fails closed."

---

## Design Decisions

### 1. Title + Promise
- **From:** "Governed AI agent tools from real API traffic" + 37-word subtitle
- **To:** "Fail-closed tools for AI agents" + 17-word subtitle
- **Why:** Lead with the differentiator (fail-closed), not the mechanism (lockfile-based)

### 2. Hero GIF
- Keep the existing side-by-side comparison GIF
- **Add a caption:** "Without Toolwright: agents silently gain new powers. With Toolwright: every tool is approved, signed, and enforced fail-closed."
- The GIF doesn't load instantly for everyone; the caption anchors meaning

### 3. Three-Tier Quickstart
- **Tier 1 — Prove it (30 sec):** `pip install toolwright && toolwright demo`
- **Tier 2 — Govern your API (5 min):** `toolwright init && toolwright ship`
- **Tier 3 — Other entry points:** OpenAPI import, HAR import, then `toolwright ship`
- **Why ship:** It's the only command that actually delivers the "plug-and-play" promise without requiring manual capture-ID copying
- **Why not leading with OpenAPI import:** `capture import` requires a manual `compile` step and capture ID copy — too fragile for a quickstart

### 4. "What You Get" — Proof Section
- **Primary:** Before/after scenario showing DENIED vs ALLOWED decisions with audit trace
- **Secondary:** Mini artifact tree (6-10 key files with one-line captions)
- **Why:** Scenario sells the outcome viscerally. Tree proves it's real and debuggable.
- **What NOT to include:** Long terminal dumps, YAML blocks, or feature explanations

### 5. "Why Toolwright" — Compact Differentiators
- 5 bullets max: fail-closed, signed approvals, drift detection, self-repairing, audit trail
- Replaces both "What Makes Toolwright Different" (5 sections) and "Runtime Enforcement" (7-point list)
- Key differentiators are already demonstrated in the proof section; this list is for skimmers
- Link to docs for the full list

### 6. Drift in CI
- Short GitHub Actions snippet for weekly drift detection
- Makes the "production-ready" story tangible in the README
- Not just a link to docs — actual runnable YAML

### 7. Claude Code Integration
- 3-line MCP config snippet (already exists, just moved higher)

### 8. Reference Section (bottom)
- Commands table (existing, moved to bottom)
- Traffic capture table (existing, moved to bottom)
- Installation variants (existing, moved to bottom)
- Runtime enforcement details (existing, moved to bottom)

---

## Proposed README Structure

| # | Section | Purpose | Approx Lines |
|---|---------|---------|--------------|
| 1 | Badges | Trust signals | 4 |
| 2 | Title + subtitle | Promise | 3 |
| 3 | Hero GIF + caption | Visual proof | 5 |
| 4 | Prove it (30 sec) | `pip install && toolwright demo` + demo GIF | 12 |
| 5 | Quick Start (5 min) | `toolwright init && toolwright ship` + other entry points | 25 |
| 6 | What You Get | DENIED/ALLOWED scenario + artifact tree | 30 |
| 7 | Why Toolwright | 5 bullets | 8 |
| 8 | Drift in CI | GitHub Actions snippet | 15 |
| 9 | Claude Code integration | MCP config | 15 |
| 10 | Reference | Commands, capture paths, install, runtime | 80 |
| 11 | Docs, Contributing, License | Links | 15 |

**Total:** ~210 lines (current: ~218 lines) — roughly the same length but entirely reordered for funnel flow.

---

## What Gets Cut

- **"The Problem" section** — The hero GIF IS the problem statement. The one-sentence subtitle covers it.
- **"How It Works" pipeline diagram** — Replaced by the proof section showing what the pipeline produces
- **"What Makes Toolwright Different" (5 subsections)** — Collapsed into 5 bullets
- **"Runtime Enforcement" (7-point list)** — Inlined into proof + bullets, details moved to reference

---

## What Gets Added (new content)

- Hero GIF caption (1 sentence)
- `toolwright ship` as the primary quickstart path (replaces the current 5-step manual path)
- "What You Get" proof section (DENIED/ALLOWED scenario + artifact tree)
- GitHub Actions drift snippet

---

## What Gets Moved (existing content, new position)

- **Commands table** → Reference section (bottom)
- **Traffic capture table** → Reference section (bottom)
- **Installation variants** → Reference section (bottom)
- **Runtime enforcement** → Reference section (bottom)
- **MCP config** → Moved up (from line 171 to ~Section 9)

---

## User Guide Changes

The user guide (`docs/user-guide.md`) needs restructuring to match:

1. **Start with "Golden Path" as a narrative** — not command reference
2. **Then "Common Entry Points"** — OpenAPI, HAR, Mint (with the actual commands and expected output)
3. **Then "Governance Model"** — how approvals work, what fail-closed means
4. **Then "Operations"** — drift, repair, rotate keys
5. **Then full command reference** — existing content, just reordered

This is a separate implementation task from the README rewrite.

---

## GIF Requirements

- **Hero comparison GIF** — already exists, keep as-is
- **Demo GIF** — already exists, keep as-is
- **Ship flow GIF** — NEW. Should show `toolwright ship` walking through the full lifecycle with the stage tracker. Use `tui-studio` skill to generate.
- **Quickstart GIF** — Consider replacing demo GIF location with a ship flow GIF to show the real adoption experience

---

## What This Does NOT Cover (deferred to CLI/UX polish phase)

- Celebration messages at milestones
- Universal next-step guidance
- Prompt friction reduction
- `toolwright ship` accepting `--openapi`, `--har`, `--url` flags for non-interactive use
- `toolwright compile --latest` for auto-discovering most recent capture
- `toolwright watch install --github` as plug-and-play drift story
- Repair flow output restructuring (diagnosis headline + safe fix + advanced view)
