# HEAL Pillar Dogfood Report -- Petstore API

**Date:** 2026-02-27
**Tester:** Claude Opus 4.6 (automated dogfood)
**Target API:** Swagger Petstore v3 (`petstore3.swagger.io`)
**Commands Tested:** `capture import`, `drift`, `health`, `repair`, `compile`

---

## Test Summary

| # | Test | Result | Notes |
|---|------|--------|-------|
| 1 | OpenAPI capture import (URL) | PASS | 19 operations imported, `--input-format openapi` required |
| 2 | Drift: identical captures | PASS | 0 drifts, exit code 0 |
| 3 | Drift: simulated schema change | PASS | 1 schema drift detected (added `weight` field) |
| 4 | Drift: report artifacts | PASS | Both JSON and Markdown reports generated |
| 5 | Compile from capture | PASS | 19 tools in tools.json, toolpack created |
| 6 | Health: write endpoints | PASS | POST/PUT/DELETE healthy (204 via OPTIONS probe) |
| 7 | Health: GET endpoints | WARN | All GET endpoints report UNHEALTHY 404 (see BUG-2) |
| 8 | Health: exit code | PASS | Exits 1 when unhealthy endpoints present |
| 9 | Repair: no context | PASS | Reports "system is healthy" |
| 10 | Repair: with drift context | PASS | 1 issue found, 1 manual patch proposed |
| 11 | Repair: artifacts | PASS | repair.json, repair.md, patch.commands.sh, diagnosis.json |
| 12 | Automated test script | PASS | 21/22 pass, 1 known warning |

**Score: 10 PASS / 0 FAIL / 2 WARN**

---

## Bugs Found

### BUG-1: OpenAPI URL auto-detection fails for remote URLs (Severity: Medium)

**File:** `/Users/thomasallicino/oss/toolwright/toolwright/cli/main.py`, line 620-635

**Symptom:** Running `toolwright capture import https://petstore3.swagger.io/api/v3/openapi.json -a petstore3.swagger.io` (without `--input-format openapi`) fails with:

```
Error: HAR file not found: https://petstore3.swagger.io/api/v3/openapi.json
```

**Root Cause:** The `_detect_openapi_format()` function at line 614 checks `source_path.exists()` on line 621. When the source is a URL (not a local file), `Path(url).exists()` returns `False`, so it falls through to the default format `"har"`. The HAR importer then tries to open the URL as a local file and fails.

**Expected:** URLs should either be auto-detected as OpenAPI (by checking Content-Type or trying to parse), or at minimum the error message should suggest using `--input-format openapi`.

**Workaround:** Use `--input-format openapi` explicitly.

**Fix:** In `_detect_openapi_format()`, detect when `source` is a URL (starts with `http://` or `https://`) and either fetch-and-probe or return `"openapi"` as the format. The `run_capture_openapi()` function already handles URL fetching correctly.

### BUG-2: Health checker HEAD probes unreliable for many APIs (Severity: Medium)

**File:** `/Users/thomasallicino/oss/toolwright/toolwright/core/health/checker.py`, lines 178-194

**Symptom:** All GET endpoints report UNHEALTHY with `[endpoint_gone]` (404) even though they are functional.

**Root Cause:** The health checker sends `HEAD` requests for GET endpoints (line 184). The Swagger Petstore server (and many API servers) does not implement HEAD for API paths, returning 404 instead. The probe URL also replaces path parameters like `{petId}` with `_probe_` (line 193), which many APIs don't handle.

**Impact:** False negatives -- healthy endpoints are reported as down. This undermines trust in the health check feature.

**Suggested Fix:**
1. When HEAD returns 404, fall back to GET (with no body) before classifying as unhealthy
2. Consider OPTIONS as an alternative probe method for GET endpoints too
3. For path-parameter endpoints, consider using a numeric placeholder like `1` instead of `_probe_`

### BUG-3 (Minor): Drift engine does not detect response status code changes (Severity: Low)

**File:** `/Users/thomasallicino/oss/toolwright/toolwright/core/drift/engine.py`, lines 300-401

**Symptom:** Changing an endpoint's response status from 200 to 404 in capture B produces no drift items.

**Root Cause:** The `_detect_modifications()` method compares auth_type, risk_tier, parameters, and response/request schemas. It does not compare `response_status`. A 200-to-404 change could indicate a broken or removed endpoint behavior even if the endpoint path/method still exists.

**Impact:** Status code changes (e.g., API returns 404 or 500 where it previously returned 200) are silently ignored.

**Suggested Fix:** Add a status code comparison in `_detect_modifications()` that flags significant status code changes (e.g., 2xx to 4xx/5xx) as breaking drift.

---

## Detailed Test Results

### 1. Capture Import

```
$ .venv/bin/toolwright capture import \
    https://petstore3.swagger.io/api/v3/openapi.json \
    -a petstore3.swagger.io \
    -n petstore_v1 \
    --input-format openapi

Capture saved: cap_20260227_fee2c3b7
  Location: .toolwright/captures/cap_20260227_fee2c3b7
  Operations: 19
  Source: OpenAPI tmpgbxlopt2.json
```

The capture correctly imported all 19 Petstore endpoints (8 pet, 4 store, 7 user). Each exchange includes request/response schemas, operation IDs, and tags from the OpenAPI spec.

### 2. Drift Detection (Identical)

```
$ .venv/bin/toolwright drift \
    --from cap_20260227_fee2c3b7 \
    --to cap_20260227_9e4c83a6 \
    --volatile-metadata

Drift Detection Complete: drift_20260227_e7cfa31a
  Total Drifts: 0
  Breaking: 0
  Exit Code: 0
```

Correctly reports zero drift between two imports of the same spec.

### 3. Drift Detection (Schema Change)

After manually adding a `weight` field to the `PUT /pet` response:

```
$ .venv/bin/toolwright drift \
    --from cap_20260227_fee2c3b7 \
    --to cap_20260227_9e4c83a6 \
    --volatile-metadata

Drift Detection Complete: drift_20260227_e7cfa31a
  Total Drifts: 1
  Schema: 1
  Exit Code: 0
```

Drift report correctly identifies:
- Type: `schema`
- Severity: `info`
- Title: "Response field added: weight"
- Endpoint: `PUT /pet`

### 4. Health Check

```
$ .venv/bin/toolwright health --tools .toolwright/artifacts/.../tools.json

  delete_pet                     healthy       204  166ms
  delete_store_order             healthy       204  108ms
  find_pet_find_by_status        UNHEALTHY     404  [endpoint_gone]  91ms
  get_pet                        UNHEALTHY     404  [endpoint_gone]  78ms
  create_pet                     healthy       204  86ms
  update_pet                     healthy       204  80ms
  ...

Some tools are unhealthy.
```

**Results breakdown:**
- 11 write endpoints (POST/PUT/DELETE): All healthy (204 via OPTIONS probe)
- 8 GET endpoints: All UNHEALTHY (404 via HEAD probe)
- Exit code: 1

The classification system works correctly (`endpoint_gone`, `auth_expired`, etc.) but the probe strategy produces false negatives for GET endpoints on APIs that don't support HEAD.

### 5. Repair

```
$ .venv/bin/toolwright repair \
    --toolpack .toolwright/toolpacks/.../toolpack.yaml \
    --from .toolwright/reports/drift.json

Repair: 1 issues found, 1 patches proposed.
  Safe: 0  Approval required: 0  Manual: 1
```

Repair correctly:
- Ingests drift report as context
- Diagnoses the schema drift issue
- Proposes a manual investigation patch
- Generates all 4 artifact files (repair.json, repair.md, patch.commands.sh, diagnosis.json)
- Includes pre-repair verification status
- Clusters issues by tool ID

**Limitation:** The `patch.commands.sh` only contains a comment (not an executable command) for manual-class patches. While this is by design, it could be confusing.

---

## Test Script

Location: `dogfood/petstore/test_heal.sh`

Run from project root:
```bash
./dogfood/petstore/test_heal.sh
```

The script:
1. Creates two Petstore captures via OpenAPI import
2. Verifies zero drift between identical captures
3. Simulates schema drift and verifies detection
4. Compiles a toolpack and verifies tools.json
5. Runs health checks and classifies results
6. Tests repair with and without context files
7. Verifies all artifact files are generated

---

## Recommendations

### Priority 1: Fix HEAD probe false negatives (BUG-2)
The health check feature is the most visible part of the HEAL pillar. False negatives for GET endpoints undermine trust. A HEAD-then-GET fallback would solve this with minimal complexity.

### Priority 2: Fix URL auto-detection for OpenAPI import (BUG-1)
Users will commonly paste an OpenAPI spec URL. The current failure is confusing. Simple fix: check if source starts with `http://`/`https://` in `_detect_openapi_format()`.

### Priority 3: Add status code drift detection (BUG-3)
Response status code changes are a common signal of API drift. Adding a comparison in `_detect_modifications()` would catch endpoints that start returning errors.

### Nice-to-have: OpenAPI base path handling
The Petstore OpenAPI spec defines paths like `/pet` but the actual API lives at `/api/v3/pet`. The OpenAPI `servers` field specifies this prefix. Including it during capture would make health probes more accurate.
