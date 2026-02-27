# Friction Log

## Format: P{severity} | What happened | Expected | Actual | Fix

| ID | Severity | Phase | Description | Expected | Actual | Fix Status |
|----|----------|-------|-------------|----------|--------|------------|
| F-001 | P1 | Hard Gate G.4 | `cask init` only shows `cask mint` path | Shows all 3 entry paths: mint, HAR import, OpenAPI import | Only shows mint | FIXED |
| F-002 | P2 | Hard Gate G.7 | `pytest-asyncio` not installed in dev venv | All tests pass on fresh install | 28 async tests fail with "async def functions not natively supported" | FIXED (installed pytest-asyncio) |
| F-003 | P2 | Track A0.2 | `cask capture import` doesn't support URLs for OpenAPI specs | `cask capture import https://...openapi.json` should fetch the URL | Treats URL as file path, fails with "not found" | **FIXED** (TDD) |
| F-004 | P1 | Track A0.4 | `capture import` + `compile` path doesn't create `toolpack.yaml` | `compile` should create a toolpack dir like `mint` does | Only creates artifacts in `.toolwright/artifacts/`; user can't use `cask serve --toolpack` | **FIXED** (TDD) |
| F-005 | P3 | Track A1.2 | DummyJSON homepage yields 0 endpoints in headless capture | Plain navigation should discover API endpoints | Homepage is static, no API calls without scripted navigation | LOGGED (user education) |
| F-006 | P2 | Track A1.11 | Bundle `client-config.json` has hardcoded absolute paths | Paths should be relative or use placeholders | `command` and `args` use absolute paths from build machine | **FIXED** (TDD) |
| F-007 | P2 | Track B4.1 | `cask serve` with mismatched lockfile/toolpack produces stack trace | Friendly error in all cases | Standard pending lockfile case handled correctly; edge case (lockfile synced against wrong tools.json) shows stack trace | **FIXED** (TDD) |
| F-008 | P3 | Track C2.1 | `curate_spec.py --check` reports drift for non-operational changes | Exit 0 when 0 operations changed | Reports "Drift detected" and exit 1 for cosmetic character changes in example text | LOGGED |
