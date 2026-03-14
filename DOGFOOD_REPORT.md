# Toolwright Dogfood Report

**Date**: 2026-03-14 (Round 2) / 2026-03-13 (Round 1)
**Branch**: feature/ceo-review-phase1

---

## Round 2 Summary (2026-03-14)

**Test method**: 5 parallel subagent teams testing lifecycle, governance, rules/kill/repair, CLI UX, and onboarding flows.

| Category | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| P0 (crash/data loss) | 0 | 0 | 0 |
| P1 (broken flow) | 6 | 0 | 6 |
| P2 (grammar/UX) | 22 | 16 | 6 |
| P3 (cosmetic) | 5 | 0 | 5 |
| **Total** | **33** | **16** | **17** |

### Fixed in Round 2 (16 issues)

**Batch 1: Pluralization + command references**
1. "1 rules" → "1 rule" in template list and apply output
2. "1 fields, 1 samples" → "1 field, 1 sample" in drift output
3. "1 endpoints" → "1 endpoint" in create output (rules count)
4. Invalid `--toolpack` flag in drift command suggestions (next_steps, quickstart, ship)
5. "repair plan" → "repair diagnose" in repair apply guidance

**Batch 2: UX polish**
6. Risk tier truncated "medi" → "med" in startup card
7. Double period in signature error message
8. "1 tools pending approval" → "1 tool pending approval"
9. `gate block` output "Rejected" → "Blocked" to match command name
10. `gate snapshot` silent success → "Baseline snapshot created."
11. `drift-status` examples show wrong command name (space → hyphen)
12. `repair --help` duplicates subcommand listing
13. `watch --help` duplicates subcommand listing
14. `serve --help` broken formatting (blank lines in \b block)

**Batch 3: Gate consistency**
15. Gate errors to stdout → stderr in 4 commands
16. No-lockfile guidance standardized across all gate commands

### Deferred Issues (17) — Need Architecture Decisions

**P1 — Architectural**
- D1: Trust store fragmentation (3 separate key stores)
- D2: `--root` ignored by `rules` commands (import-time default)
- D3: `--root` ignored by `kill`/`enable`/`breaker-status`/`quarantine`
- D4: `gate sync` does not re-sign stale signatures
- D5: `repair diagnose` output disconnected from `repair plan`/`apply`
- D6: `gate allow --all` blocks when rejected tools exist

**P2 — UX improvements**
- D7: `quickstart` not exposed as CLI command
- D8: `doctor` and `init` hidden from main `--help`
- D9: Next steps inconsistency across flows
- D10: `rules --help` leaks CWD-resolved default path
- D11: `gate check` suggests wrong fix for rejected tools

**P3 — Cosmetic**
- D12: `repair apply` is a stub that claims to apply patches
- D13: `rules add -k prerequisite` allows empty `--requires`
- D14: `rules add -k parameter` allows empty `--param-name`
- D15: `kill` accepts arbitrary tool IDs without validation
- D16: macOS-specific path in create output
- D17: `config` help puts examples after options

---

## Round 1 Summary (2026-03-13)

**Test method**: Systematic manual CLI testing + automated test suite analysis

| Category | Found | Fixed |
|----------|-------|-------|
| P0 (crash/data loss) | 1 | 1 |
| P1 (broken flow) | 8 | 8 |
| P2 (grammar/UX) | 18 | 18 |
| P3 (cosmetic) | 15 | 15 |
| **Total** | **42** | **42** |

All 42 Round 1 issues were fixed, including:
- `serve --max-risk` crash on "safe" tier
- Orphaned worktree test/source files (11 files removed)
- Bare name resolution (`--toolpack github`) across 10 CLI files
- Type preservation through parser → aggregator → compiler pipeline
- Pluralization fixes across create, approve, gate review
- Dynamic step numbering in create output
- Empty tool ID validation in breaker-status
- Security verification: 7/7 attack vectors blocked

---

## Cumulative Stats

| Metric | Value |
|--------|-------|
| Total issues found | 75 |
| Total issues fixed | 58 |
| Deferred (architectural) | 17 |
| Test suite | 3097 passing |
| Security attacks blocked | 7/7 |
