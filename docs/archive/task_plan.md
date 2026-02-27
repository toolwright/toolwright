# Task Plan: Toolwright v1.1 Robustness and Plug-and-Play Setup

## Goal
Ship a decision-complete v1.1 robustness milestone that improves first-run UX and verification reliability without breaking the v1 governance wedge:

`mint -> diff -> gate -> run -> drift -> verify`

## Why this plan
v1 contracts are largely in place, but adoption risk remains in two areas:
1. Setup friction before users reach first success.
2. Provenance false-confidence and ambiguous candidate selection.

## Success criteria
1. New users can run one command (`cask start`) and immediately receive one valid next command toward a real mint run.
2. Setup diagnostics return deterministic fix-it strings for common failures.
3. Capture quality outputs are deterministic and auditable (`coverage_report.json`, `capture_quality.json`).
4. Provenance “pass” is strict and stable; uncertain cases are explicitly `unknown`.
5. CI has clear local-quick and release-strict verification gates.

## Non-goals
1. General autonomous browsing agents.
2. MFA bypass or anti-bot circumvention.
3. Expanding runtime to a full gateway product.

## Locked v1.1 contracts (must hold)
1. `cask start` default is non-interactive setup and readiness checks (unless browser installation requires interaction).
2. `cask start --non-interactive` must never prompt.
3. `cask start --json` emits machine-readable results including next-command output.
4. Auth artifacts are profile-scoped:
   - `<root>/state/auth/<profile>/auth_profile.yaml`
   - `<root>/state/auth/<profile>/storage_state.json`
   - `<root>/state/auth/<profile>/persistent_context_ref.json`
5. `auth_profile.yaml` is versioned (`version: 1`) with required fields and deterministic validation.
6. Probe packs are read-safe by design and must not finalize destructive actions.
7. Challenge detection is explicit in `capture_quality.json` (`challenge_detected`, `challenge_kind`, `challenge_evidence`, `degraded_capture`).
8. Noise suppression is deterministic with rule IDs from versioned `noise_signatures.yaml`.
9. User-owned `noise_overrides.yaml` can override suppression outcomes deterministically.
10. Provenance strong signals are fixed and scored deterministically (timing, payload_match, schema_match, rerun_consistency, request_role_match).
11. Dominant source-kind is defined as highest normalized score mass by source kind.
12. Strict provenance pass requires dominant `http_response` plus two strong signals.
13. Fixture thresholds live in `fixtures/<name>/fixture.yaml` (not hardcoded in tests).
14. CI modes are explicit:
   - local quick gate: 1 run, unknown budget <= 20%
   - release strict gate: 3 runs, unknown budget <= 10%
15. Bundle/export boundaries remain secret-safe and unchanged from v1 hard contracts.

## Execution phases

### Phase 0: Plan and baseline lock (completed)
- [x] Re-read agent/process rules (`AGENTS.md`, planning-with-files, using-superpowers).
- [x] Verify current command surface and current gaps.
- [x] Confirm v1 baseline still intact before v1.1 work.

### Phase 1: Onboarding command and fix-it UX (in progress)
- [ ] Add `start` command (`cask start`) with deterministic readiness checks.
- [ ] Add `--non-interactive`, `--json`, and `--skip-browser-install` behavior.
- [ ] Emit one canonical next command (no multi-path branching by default).
- [ ] Add fix-it mappings for: missing browsers, stale lock, auth required, unknown signer, weak permissions.
- [ ] Add `state perms fix` helper (or lock deterministic manual fix text if helper deferred).

### Phase 2: Auth profile contract hardening (pending)
- [ ] Implement versioned auth profile schema and validation.
- [ ] Enforce profile-scoped storage paths.
- [ ] Add `cask auth status` with `last_validated_at` and storage-state load status.
- [ ] Ensure auth subtree is excluded from export/bundle outputs.

### Phase 3: Deep deterministic capture v2 (pending)
- [ ] Define deterministic probe pack with step IDs (search, facet, pagination, detail).
- [ ] Emit classifier labels and confidence/review flags.
- [ ] Guarantee `coverage_report.json` + `capture_quality.json` generation.
- [ ] Enforce write-safe boundary (never finalize irreversible operations).
- [ ] Add challenge detection contract and evidence refs.

### Phase 4: Noise suppression + overrides (pending)
- [ ] Introduce versioned `noise_signatures.yaml` with rule IDs.
- [ ] Add deterministic suppression attribution in outputs.
- [ ] Implement `noise_overrides.yaml` (user-owned) with explicit override IDs.
- [ ] Emit pre- and post-suppression noise ratios and gate on post-suppression.
- [ ] Lock definitions:
  - business endpoint
  - business actions discovered
  - noise endpoint

### Phase 5: Provenance v2 robustness (pending)
- [ ] Implement fixed strong-signal scoring model.
- [ ] Add deterministic dominant source-kind calculation.
- [ ] Add stable `why_not_pass` ordering.
- [ ] Support local fast mode (1 run) and strict mode (3 runs).
- [ ] Ensure strict pass cannot occur from assertion-text contamination.

### Phase 6: Fixtures + CI gates (pending)
- [ ] Add per-fixture metadata in `fixtures/<name>/fixture.yaml`.
- [ ] Implement local quick gate runner.
- [ ] Implement release strict gate runner (3-run consistency).
- [ ] Add deterministic tolerance rules for rerun stability.
- [ ] Keep `diff --format github-md` and GitHub gate action coverage green.

### Phase 7: Docs/UX truth pass (pending)
- [ ] Update README and user guide with `cask start` first-run path.
- [ ] Add explicit “local quick vs release strict” guidance.
- [ ] Add auth profile + challenge + noise override docs.
- [ ] Verify all “shipped” claims map to tests and CLI behavior.

### Phase 8: Validation and release-readiness (pending)
- [ ] Run full tests, lint, and mypy.
- [ ] Run manual smoke on fresh root and inspect generated artifacts directly.
- [ ] Run at least one real-site eval batch and compare outputs to expectations.
- [ ] Record residual risks and follow-up work for v1.2.

## Testing matrix (required)
1. CLI behavior: `help`, `help-all`, alias parity, `start` flags.
2. Setup diagnostics: deterministic fix-it output contract.
3. Auth profile schema/path validation tests.
4. Probe safety tests (no irreversible write completion in fixtures).
5. Noise suppression and override determinism tests.
6. Provenance ranking and source-kind tests, including false-pass regression guards.
7. Rerun consistency tests for strict mode.
8. CI gate exit-code and threshold tests.
9. Redaction and bundle boundary regression tests.

## Dependencies and risks
1. Live-site anti-bot and auth challenges can degrade capture depth.
2. Playwright/browser install environment variance remains a setup risk.
3. Provenance strictness may increase `unknown` rates before quality tuning.

## Current phase
Phase 1 is now active.
