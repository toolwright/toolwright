# Verification Spec (v1)

`toolwright verify` provides deterministic verification reports for capability governance and CI gating.

## Modes

- `contracts`
- `replay`
- `outcomes`
- `provenance`
- `all`

`all` includes provenance when both playbook and UI assertions are provided.

## Provenance goal

Map UI output to ranked API/tool candidates with evidence.

## Inputs

### Playbook

Provided with `--playbook`.

See `docs/playbook-spec.md`.

### UI assertions

Provided with `--ui-assertions`.

Supported structure:

```yaml
version: "1.0"
ui_assertions:
  - name: search_results_list
    locator:
      by: role
      value: "list"
    expect:
      type: contains_text
      value: "laptop"
    capture_window_ms: 1500
```

Supported locator `by` values:

- `role`, `label`, `text`, `css`, `xpath`

Supported expectation types:

- `contains_text`, `equals`, `regex`, `json_shape`

## Candidate shape

Each candidate contains:

- `tool_id`
- `request_fingerprint`
- `score`
- `source_kind`
- `signals`:
  - `timing`
  - `content_match`
  - `shape_match`
  - `repetition`
- `evidence_refs`

## Source kind taxonomy

- `http_response`
- `cache_or_sw`
- `websocket_or_sse`
- `local_state`

## Status rules

- `pass`: threshold met and at least two strong signals
- `unknown`: plausible candidates exist but threshold not met or non-http dominates
- `fail`: no plausible candidates or assertion state not reached

## Defaults

- `top_k=5`
- `min_confidence=0.70`
- `capture_window_ms=1500`
- `unknown_budget=20%`

## Report contract

Verification emits a JSON report containing:

- mode/config metadata
- section status for each mode
- provenance candidate rankings and chosen candidate
- governance mode (`approved` or `pre-approval`)
- exit code classification

## Exit codes

- `0`: pass
- `1`: gated non-breaking issues
- `2`: breaking issues
- `3`: invalid input/config
