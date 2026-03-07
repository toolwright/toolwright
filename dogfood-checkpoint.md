# Dogfood Checkpoint

## Status: ALL PHASES COMPLETE

**Total findings:** 83 (F-001 through F-083)
**Final report:** [docs/dogfood/DOGFOOD_REPORT.md](docs/dogfood/DOGFOOD_REPORT.md)
**Detailed findings:** [docs/dogfood/findings.md](docs/dogfood/findings.md)

---

## Phase Completion

| Phase | Focus | Status | Findings |
|-------|-------|--------|----------|
| 0 | CLI verification | COMPLETE | F-001 — F-008 |
| 1A-F | GitHub full pipeline | COMPLETE | F-009 — F-027 |
| 2A | Capture path comparison | COMPLETE | F-063 — F-074 |
| 2B | Shopify gate workflow | COMPLETE | F-028 — F-031 |
| 2C | Live Shopify testing | COMPLETE | F-032 — F-038 |
| 2D | Stress testing | COMPLETE | F-039 — F-041 |
| 2E | Drift & repair | COMPLETE | F-042 — F-047 |
| 2F | Reconciliation | COMPLETE | F-048 — F-054 |
| 2G | Endurance (180s) | COMPLETE | F-075 — F-083 |
| 3 | Extra-header auth | COMPLETE | F-055 — F-062 |

## What's Done

### Phase 0: CLI Verification (COMPLETE)
- All 35+ commands verified. 8 findings.

### Phase 1: GitHub Dogfood (COMPLETE)
- **Phase 1A-F:** GitHub OpenAPI (1079 ops -> 1048 tools). Full pipeline verified. 27 findings, 1 blocker (fixed).

### Post-Phase 1 Fixes (ALL FIXED)
- **F-018 FIXED:** `--schema-validation` flag (strict|warn|off, default warn). Verified: 0/1048 outputSchema in warn mode.
- **F-017 FIXED:** Auth env var warning on serve startup. Verified with real toolpack.
- **F-019 FIXED:** Query params in OpenAPI synthetic URLs. Verified: 101/1079 GitHub exchanges now carry query params.

### GitHub Re-Import with F-019 Fix
Re-imported GitHub OpenAPI spec after F-019 fix:
- **Before:** 981/1048 tools with input properties, 3128 total properties
- **After:** 998/1048 tools with input properties, 3329 total properties (+201)
- **101 tools** gained query param inputs (e.g., `get_advisories` +15, `get_issues` +7, `get_search_repositories` +2)
- New toolpack: `github-2` at `~/toolwright-dogfood/github/.toolwright/toolpacks/github-2/`

### Phase 2: Shopify Dogfood (COMPLETE)

**Phase 2A: Capture Path Comparison**
- All 4 capture paths available (HAR, OpenAPI, Playwright, OTEL)
- Full HAR→compile pipeline works: 10 real API calls → HAR file → import → compile → 10 tools
- HAR captures have response bodies + timing; OpenAPI has neither
- HAR tools lack input params and method/path (inferior to OpenAPI for tool quality)
- `HARParser.parse_file()` API contract bug: crashes on `str` input (F-063)
- HAR captures don't redact auth tokens (F-068)

**Phase 2B: Gate Workflow**
- Sync (1183 pending) -> Allow all -> Check (exit 0). Clean.
- Risk classification unusable: template host `{shop}.myshopify.com` → all tools `critical` (F-028)

**Phase 2C: Live Agent Testing**
- 1183 tools listed via MCP ListTools
- Live testing against `toolwright-dogfood.myshopify.com`:
  - 13/25 endpoints succeed (200)
  - 9/25 scope-blocked (403 on customer data)
  - 3/25 version-broken (404 on unstable API version)
- 5 blockers found: deny_admin rule, confirmation cascade, POST body wrapping, missing endpoints, old spec versions

**Phase 2D: Stress Testing**
- Budget double-consumption on confirmed calls (F-039)
- Rate limit double-counting from two-step confirmation flow (F-040)

**Phase 2E: Drift Detection & Repair**
- Snapshot lifecycle works: 9 artifact files captured, timestamped IDs
- Rollback fully restores state after drift injection (verified with live API call)
- Drift detection works: removed tools + method changes detected
- RepairEngine detects tampering but proposes 0 patches (F-045)

**Phase 2F: Reconciliation**
- ReconcileLoop lifecycle works end-to-end (init, start, probe, persist, stop)
- Circuit breaker + reconcile integration works
- Health probes don't send auth → false AUTH_EXPIRED on authenticated APIs (F-048)
- Watch CLI commands available (status + log)

**Phase 2G: Endurance Testing (180s)**
- 15 tools (8 GET, 4 POST, 3 DELETE) monitored for 3 minutes
- 18 reconcile cycles, 0 errors, 122 events
- 7 healthy / 8 unhealthy (stable after convergence)
- State persistence: memory/disk match perfectly
- State resume: new loop loads persisted state and continues
- Event log: all probe outcomes captured (90 healthy + 32 unhealthy)
- Circuit breaker: no quarantines (threshold not reached, 4 consecutive failures)

### Phase 3: Extra-Header Verification (COMPLETE)
- Extra-header injection works end-to-end (CLI parse → server → upstream → 200)
- No header values leak into MCP responses or audit logs
- Multiple extra headers work without interference
- Extra-header can override Authorization (last-wins, intentional)
- **Critical finding:** Auth env var convention (`TOOLWRIGHT_AUTH_*`) incompatible with APIs using custom auth headers

### Phase 4: Documentation Quality Audit (COMPLETE)
Found 3 critical, 14 friction, 8 polish issues. All critical issues fixed.

## Findings Severity Summary

| Severity | Count | Fixed | Open |
|----------|-------|-------|------|
| Blockers | 6 | 5 | 1 |
| Friction | 20 | 3 | 17 |
| Polish | 4 | 0 | 4 |
| Missing Features | 1 | 0 | 1 |
| Verified Working | 25 | — | — |
| Summary entries | 7 | — | — |
| Works Great | 20 | — | — |

### Dogfood Blocker Fixes (branch: fix/dogfood-blockers)

| Finding | Issue | Fix | Test File |
|---------|-------|-----|-----------|
| F-032 | deny_admin rule blocks all Shopify endpoints | Removed deny_admin auto-generation from policy compiler | `test_policy_generation.py` |
| F-028/F-035 | All GET tools classified critical due to /admin/ path | Read-only methods (GET/HEAD/OPTIONS) capped at medium risk | `test_risk_classification.py` |
| F-039/F-040 | Budget double-counting on confirmed calls | dry_run evaluation + explicit consume_budget() on final ALLOW | `test_budget_double_counting.py` |
| F-037 | POST body not wrapped in resource key | Detect envelope wrapper at compile, apply at execution time | `test_body_wrapping.py` |

## Key Paths

### GitHub
- Toolpack (original): `~/toolwright-dogfood/github/.toolwright/toolpacks/github/toolpack.yaml`
- Toolpack (re-imported with F-019): `~/toolwright-dogfood/github/.toolwright/toolpacks/github-2/toolpack.yaml`
- MCP config: `/Users/thomasallicino/oss/toolwright/.mcp.json`

### Shopify
- Toolpack: `~/toolwright-dogfood/shopify/.toolwright/toolpacks/toolwright-dogfood/toolpack.yaml`
- Spec: `~/toolwright-dogfood/shopify/shopify_openapi.yaml`
- Store: `toolwright-dogfood.myshopify.com`
