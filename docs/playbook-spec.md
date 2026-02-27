# Playbook Spec (v1)

This document defines the deterministic playbook format used by `toolwright verify --mode provenance`.

## File format

- YAML or JSON
- Required top-level keys:
  - `version` (string)
  - `steps` (array)

## Supported step types (v1)

- `goto`
- `click`
- `fill`
- `wait`
- `select`
- `submit`
- `scroll`
- `extract`

Unsupported step types fail verification input validation.

## Step schema

Each step is a mapping with:

- `type` (required)
- `name` (optional, recommended)
- `timeout_ms` (optional, default runner timeout)
- type-specific parameters (for example `url`, `locator`, `value`)

## Determinism rules

- Use stable URL targets and deterministic test data.
- Prefer explicit waits tied to deterministic conditions.
- Avoid randomized selectors or time-based brittle waits.
- Avoid free-form script execution in v1 playbooks.

## Locator policy

When a step needs a locator, use this preference order:

1. `role`
2. `label`
3. `text`
4. `css`
5. `xpath`

## Versioning

- Current schema version: `1.0`
- Version mismatch must fail with an actionable error.
- Future migrations should be performed via `toolwright migrate`.
