# CI Gate Policy (v1)

This file defines default CI gate behavior for Toolwright artifacts.

## Required CI checks

1. `toolwright diff --format github-md`
2. `toolwright gate check --lockfile <approved-lockfile>`
3. `toolwright drift --baseline <baseline> --capture-id <capture-id>`
4. `toolwright verify --mode all` (when verification inputs are available)
5. `toolwright lint` for artifact hygiene

## Exit code policy

Common exit code semantics:

- `0`: pass
- `1`: gated non-breaking issue
- `2`: breaking issue
- `3`: invalid input/config

## Breaking gate conditions

Breaking (exit `2`) includes:

- contract/schema breaks
- unapproved capability expansion
- approval-signature contract violations
- redaction leak detection

## Non-breaking gated conditions

Non-breaking gated (exit `1`) includes:

- unknown provenance ratio over budget
- policy hygiene/lint failures
- gated drift changes requiring review

## Provenance budget

Default unknown provenance budget is `20%` of assertions.

If `unknown_ratio > 0.20`, CI should fail with non-breaking gated status.

## GitHub integration

Use `.github/actions/toolwright-gate/action.yml` for reusable governance checks.
