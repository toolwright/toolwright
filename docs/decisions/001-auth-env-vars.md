# Decision 001: Environment Variables as the Single Auth Mechanism

**Status:** Accepted
**Date:** 2026-03-01

## Context

Toolwright injects authentication headers into upstream API requests at runtime. The question is how users configure those credentials.

## Decision

Environment variables are the single auth mechanism. No alternative storage (config files, system keychain, OAuth browser flows) will be added.

The auth pipeline:

1. **Discovery** — `toolwright mint` probe output detects auth requirements (401/403, WWW-Authenticate) and prints exact `export` commands
2. **Configuration** — User sets `TOOLWRIGHT_AUTH_<HOST>` env vars (or global `TOOLWRIGHT_AUTH_HEADER`)
3. **Validation** — `toolwright auth check` verifies env vars are set and optionally probes hosts
4. **Injection** — `toolwright serve` resolves per-host env vars at request time and injects the `Authorization` header

Priority order: `--auth` CLI flag > `TOOLWRIGHT_AUTH_<HOST>` per-host env var > `TOOLWRIGHT_AUTH_HEADER` global fallback.

## Rationale

**Env vars are the CLI auth standard.** Every developer knows `export FOO=bar`. Every CI system supports env var injection. Every secrets manager can populate them. Docker, Heroku, Vercel, AWS Lambda, GitHub Actions are all env-var-native.

**Config files risk credential leaks.** Users will commit `.toolwrightrc` or `toolwright.toml` to git. You'd need `.gitignore` scaffolding, plaintext secret warnings, potentially encryption. All that work to solve a problem env vars don't have. Tools that store auth in config files (`.npmrc` with tokens) are a constant source of credential leaks.

**System keychain breaks CI.** macOS Keychain, Windows Credential Manager, and libsecret provide better security for desktop users but don't work in Docker, headless servers, or CI pipelines. Supporting both would fragment the auth story into two code paths.

**OAuth browser flows are wrong for this stage.** Enterprise customers will eventually want SSO, short-lived tokens, and identity federation. That's a multi-week per-provider project. The current user base is developers dogfooding a CLI tool; they don't need or want a browser popup to authenticate.

## Known Gap

Probe output only appears during `toolwright mint`. Users configuring auth for `toolwright serve` on an existing toolpack get no interactive guidance. They must know the naming convention (`TOOLWRIGHT_AUTH_` + uppercased host, dots/hyphens replaced with underscores) from docs or the startup warning.

This is mitigated by:
- Startup warnings that print exact `export` commands for missing auth
- The naming convention being predictable and documented
- `toolwright auth check` validating configuration at any time

A future P2 improvement (`toolwright auth set <host>`) will close this gap by providing an interactive prompt that writes to a `.env` file in the toolpack directory. See ROADMAP.md.

## Alternatives Considered

| Alternative | Why not |
|---|---|
| Config files (`.toolwrightrc`, TOML) | Credential leak risk; needs `.gitignore` scaffolding and encryption |
| System keychain | Breaks CI/Docker/headless; fragments auth into two code paths |
| OAuth browser flow | Multi-week per-provider work; wrong for current stage and user base |
| `.env` file in toolpack | Planned as P2 quality-of-life addition, not a replacement for env vars |
