# Findings: Toolwright v1.1 Robustness Setup

## Date
2026-02-10

## Baseline reality confirmed
1. Canonical help surface is in place and clean:
   - Flagship commands in default help.
   - Advanced commands only in `--help-all`.
2. Compatibility aliases are present (`plan`, `approve`, `mcp meta`).
3. `cask` alias works.
4. `cask start` is not implemented yet (`No such command 'start'`).
5. v1 docs/spec artifacts for verification/redaction/CI/scopes already exist under `docs/`.

## Key gaps for v1.1 (adoption-critical)
1. Onboarding speed:
   - No single setup command with deterministic diagnostics and next-step output.
2. Provenance trust:
   - Need stricter pass criteria and clearer “unknown” explanations to avoid false confidence.
3. Capture depth clarity:
   - Need deterministic probe-pack outputs and explicitly defined coverage metrics.
4. Noise handling:
   - Need deterministic suppression + user override model with attribution.
5. Auth profile ergonomics:
   - Need profile-scoped file contract and schema-level guarantees.

## Decisions locked for this execution
1. v1 wedge remains unchanged; v1.1 is robustness and UX hardening.
2. `cask start` becomes the primary first-run entrypoint.
3. Provenance keeps conservative posture: prefer `unknown` over unsafe pass.
4. Deterministic outputs and auditable rule IDs are mandatory for suppression/classification.
5. CI split remains explicit:
   - Local quick checks for fast iteration.
   - Strict multi-run checks for release confidence.

## External research
- None required for this setup pass; decisions derive from current repo state and locked product direction.

## Risks to watch
1. Live sites can block deterministic capture due to anti-bot/login friction.
2. Overly strict provenance thresholds may increase unknowns before classifier/signal tuning.
3. Setup command can become bloated if too many optional flows are embedded in first-run path.
