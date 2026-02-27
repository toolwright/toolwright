# Toolwright UX Friction Audit -- Error Paths

**Date**: 2026-02-27
**Auditor**: Claude Opus 4.6 (automated)
**Script**: `dogfood/friction_audit.sh`

## Summary

| Metric | Count |
|--------|-------|
| Scenarios tested | 12 (11 required + 1 bonus) |
| Individual checks | 35 |
| PASS | 28 |
| FAIL | 5 |
| WARN | 2 |

Overall error UX quality is **solid**: no raw Python tracebacks, most Click-based validation is clean, and several custom error messages are genuinely helpful. The main gaps are:

1. **Missing "what to do next" hints** in several error messages
2. **Pydantic validation errors leak** when toolpack.yaml is malformed
3. **`gate check` does not suggest `gate allow`** (the most natural next step)
4. **`kill` / `enable` silently create directories and succeed on phantom tools** with no validation

---

## Scenario Results

### Scenario 1: `serve --tools nonexistent.json`

| Check | Result |
|-------|--------|
| **Command** | `toolwright serve --tools nonexistent.json` |
| **Output** | `Error: Tools manifest not found: nonexistent.json` |
| Helpful? | **PASS** -- clearly says what is missing |
| Suggests fix? | **FAIL** -- should say: `Run 'toolwright capture import <file>' or 'toolwright mint <url>' to create a tools manifest.` |
| Stack trace? | **PASS** -- clean |

**Suggested improvement**: Append a one-liner like:
```
Hint: Create one with 'toolwright mint <url>' or 'toolwright capture import <file>'.
```

---

### Scenario 2: `gate check` with pending tools

| Check | Result |
|-------|--------|
| **Command** | `toolwright gate check --lockfile <path>` |
| **Output** | `FAIL: Pending approval: get_pet, list_pets` |
| Helpful? | **PASS** -- lists the pending tool names |
| Suggests fix? | **FAIL** -- does not say `Run: toolwright gate allow --all` or `toolwright gate allow get_pet list_pets` |
| Stack trace? | **PASS** -- clean |

**Suggested improvement**: Append:
```
Run: toolwright gate allow --all --lockfile <path>
```
This is the most critical fix -- CI pipelines and new users will see this error most often.

---

### Scenario 3: `compile --capture nonexistent_capture_id`

| Check | Result |
|-------|--------|
| **Command** | `toolwright compile --capture nonexistent_capture_id` |
| **Output** | `Error: Capture not found: nonexistent_capture_id` |
| Helpful? | **PASS** -- clear |
| Suggests fix? | **WARN** -- no explicit hint |
| Stack trace? | **PASS** -- clean |

**Suggested improvement**: Append:
```
Hint: List captures with 'toolwright capture list' or create one with 'toolwright capture import <file>'.
```

---

### Scenario 4: `status` in empty directory

| Check | Result |
|-------|--------|
| **Command** | `toolwright status` (in a directory with no `.toolwright/`) |
| **Output** | `No toolpacks found. Run 'toolwright mint' or 'toolwright init' first.` |
| Helpful? | **PASS** |
| Suggests fix? | **PASS** -- suggests `mint` and `init` |
| Stack trace? | **PASS** |

**Verdict**: This is the gold standard for error messages in the project. Other commands should follow this pattern.

---

### Scenario 5: `gate sync` with no args

| Check | Result |
|-------|--------|
| **Command** | `toolwright gate sync` |
| **Output** | `Error: Provide either --toolpack or --tools.` (with usage header) |
| Helpful? | **PASS** |
| Suggests fix? | **PASS** -- tells you exactly what options are needed |
| Stack trace? | **PASS** |

**Verdict**: Excellent. Clean custom error message.

---

### Scenario 6: `gate allow nonexistent_tool`

| Check | Result |
|-------|--------|
| **Command** | `toolwright gate allow nonexistent_tool --lockfile <path>` |
| **Output** | `Not found: nonexistent_tool` |
| Helpful? | **PASS** -- identifies the bad input |
| Suggests fix? | **FAIL** -- should list available tool names from the lockfile |
| Stack trace? | **PASS** |

**Suggested improvement**: Append:
```
Available tools: list_pets, get_pet
```

---

### Scenario 7: `health` with no `--tools`

| Check | Result |
|-------|--------|
| **Command** | `toolwright health` |
| **Output** | `Error: Missing option '--tools'.` (with usage header) |
| Helpful? | **PASS** |
| Suggests fix? | **PASS** -- Click names the missing option |
| Stack trace? | **PASS** |

**Verdict**: Clean. Standard Click behavior.

---

### Scenario 8: `serve --toolpack /nonexistent/toolpack.yaml`

| Check | Result |
|-------|--------|
| **Command** | `toolwright serve --toolpack /nonexistent/toolpack.yaml` |
| **Output** | `Error: Invalid value for '--toolpack': Path '/nonexistent/toolpack.yaml' does not exist.` |
| Helpful? | **PASS** |
| Suggests fix? | **PASS** -- the `Try --help` line is present |
| Stack trace? | **PASS** |

**Verdict**: Clean. Click's `exists=True` validation is appropriate here.

---

### Scenario 9: `config` with no `--toolpack`

| Check | Result |
|-------|--------|
| **Command** | `toolwright config` |
| **Output** | `Error: Missing option '--toolpack'.` (with usage header) |
| Helpful? | **PASS** |
| Suggests fix? | **PASS** |
| Stack trace? | **PASS** |

**Verdict**: Clean. Could optionally auto-discover toolpacks in `.toolwright/toolpacks/` but the error is acceptable.

---

### Scenario 10: `kill` with nonexistent breaker state path

| Check | Result |
|-------|--------|
| **Command** | `toolwright kill some_tool --breaker-state /tmp/nonexistent-dir/breakers.json` |
| **Output** | `Tool 'some_tool' killed (circuit breaker forced open). Reason: manual kill` |
| Helpful? | N/A (succeeds) |
| Suggests fix? | N/A |
| Stack trace? | **PASS** |

**Issue (WARN)**: The `kill` command silently creates the entire directory tree and the breaker state file. It also happily kills tools that don't exist in any manifest. While auto-creating the state file may be intentional for first-use convenience, killing phantom tools with no warning could mask typos. Same applies to `enable`.

**Suggested improvement**: Validate tool_id against a manifest if `--tools` or `--toolpack` is also provided, or at minimum warn:
```
Warning: Tool 'some_tool' is not in any known manifest. Kill applied anyway.
```

---

### Scenario 11: `rules add --kind prerequisite` (missing `--description`)

| Check | Result |
|-------|--------|
| **Command** | `toolwright rules add --kind prerequisite` |
| **Output** | `Error: Missing option '--description' / '-d'.` (with usage header) |
| Helpful? | **PASS** |
| Suggests fix? | **PASS** |
| Stack trace? | **PASS** |

**Verdict**: Clean.

---

### Bonus: Malformed `toolpack.yaml` (Pydantic validation error leak)

| Check | Result |
|-------|--------|
| **Command** | `toolwright gate sync --toolpack <malformed.yaml>` |
| **Output** | `Error loading toolpack: 7 validation errors for Toolpack` followed by raw Pydantic `Field required` messages with `input_value=...` dictionaries and `pydantic.dev` URLs |
| Helpful? | **FAIL** -- user sees internal model field names (`toolpack_id`, `artifact_id`, `capture_id`) that are never mentioned in any docs |
| Suggests fix? | **FAIL** -- no guidance on what a valid toolpack.yaml looks like |
| Stack trace? | **FAIL** -- leaks Pydantic internals and links to `errors.pydantic.dev` |

**This is the most serious UX issue found in the audit.** A user with a hand-edited or outdated toolpack.yaml will see 20+ lines of Pydantic internals that look like a bug report.

**Suggested improvement**: Catch `pydantic.ValidationError` in `load_toolpack()` and produce:
```
Error: Invalid toolpack.yaml -- missing required fields: toolpack_id, created_at, capture_id, ...

Toolpacks are created by 'toolwright mint' or 'toolwright compile'. If you need to
edit one manually, see: toolwright compile --help
```

---

## Additional Findings (from extra edge-case testing)

### Extra A: `serve` with tools.json but no lockfile

| **Command** | `toolwright serve --tools tools.json` (no lockfile present) |
| **Output** | Detailed multi-line error with exact copy-paste commands |

**Verdict**: **Excellent**. This is the best error message in the entire CLI. It tells you exactly what happened, gives you the exact commands to run, and formats them as a step-by-step recipe. All other error messages should aspire to this quality.

### Extra B: `serve` with pending (unapproved) lockfile

| **Command** | `toolwright serve --tools tools.json --lockfile <pending-lockfile>` |
| **Output** | (exit 0, server starts) |

**Issue**: The MCP server starts and exposes tools even though none are approved. This may be by design (lockfile presence = intent to govern, not a hard gate at serve time), but it is surprising given the governance-first philosophy. At minimum a warning like `Warning: 2 of 2 tools are pending approval` would be helpful.

### Extra C: `enable` on nonexistent tool

| **Command** | `toolwright enable nonexistent_tool` |
| **Output** | `Tool 'nonexistent_tool' enabled (circuit breaker closed).` |

**Issue**: Same phantom-tool problem as `kill`. Success message on a tool that was never killed and doesn't exist.

### Extra D: `gate check` with nonexistent lockfile

| **Command** | `toolwright gate check --lockfile /nonexistent.yaml` |
| **Output** | `No lockfile found at: /nonexistent.yaml` + `Run 'toolwright gate sync' first.` (exit 2) |

**Verdict**: Clean. Good error message with fix suggestion.

---

## Severity-Ranked Issues

| # | Severity | Scenario | Issue |
|---|----------|----------|-------|
| 1 | **P1** | Bonus | Pydantic validation errors leak to user when toolpack.yaml is malformed |
| 2 | **P1** | 2 | `gate check` does not suggest `gate allow` command (blocks CI adoption) |
| 3 | **P2** | 1 | `serve --tools nonexistent.json` does not suggest how to create a manifest |
| 4 | **P2** | 6 | `gate allow <bad-tool>` does not list available tools |
| 5 | **P2** | Extra B | `serve` with pending lockfile starts without warning |
| 6 | **P3** | 3 | `compile --capture <bad-id>` does not hint at `capture list` |
| 7 | **P3** | 10 / Extra C | `kill` and `enable` succeed on phantom tools with no validation |

---

## Recommendations

1. **Wrap Pydantic errors in `load_toolpack()`** -- catch `ValidationError` and emit a user-friendly summary listing the missing fields and a pointer to docs or `mint` / `compile`.

2. **Add fix-suggestion to `gate check`** -- when pending tools exist, append: `Run: toolwright gate allow --all --lockfile <path>`.

3. **Add "Available tools: ..." to `gate allow` "Not found"** -- helps catch typos.

4. **Add "Hint: ..." lines to `serve`, `compile` errors** -- follow the pattern of Scenario 4 (`status`) which is the gold standard.

5. **Warn on serve with pending lockfile** -- at minimum a stderr warning.

6. **Consider validating tool_id for `kill` / `enable`** if a manifest/lockfile is discoverable.
