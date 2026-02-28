# Roadmap

Post-dogfood engineering backlog. Items will be prioritized based on real-world usage findings.

## Deferred from hardening (known gaps)

- **Hash-chained audit log** — P3, append-only tamper evidence for audit trail
- **Real Windows CI** — Platform guards are in place but unverified without a Windows runner

## From architecture review feedback

- **Flapping detection** — Per-tool ring buffer of recent repair fingerprints. If same tool
  repaired >3 times in 30 minutes, escalate to APPROVAL_REQUIRED and log flapping warning
- **Explicit escalation state machine** — Unify repair classification + circuit breaker into
  single per-tool state: HEALTHY → AUTO_HEALING → NEEDS_APPROVAL → MANUAL → QUARANTINED
- **Automation budget** — If total drift events across all tools exceed threshold in time
  window, ratchet auto-heal down globally and require approvals
- **Canary validation** — Run contract verification against patched toolpack before promoting
  to active runtime (verify-then-promote, not traffic splitting)
- **Post-apply auto-rollback** — If post-apply probe fails, auto-restore from pre-patch
  snapshot and escalate to APPROVAL_REQUIRED
- **MAPE-K documentation** — Document reconciliation as Monitor/Analyze/Plan/Execute/Knowledge
  loop in architecture docs

## Known limitations

- **GraphQL APIs** — Single POST endpoint with operation in body collapses to one tool.
  Toolwright cannot meaningfully govern GraphQL APIs today.
- **Browser bot detection** — Cloudflare/Akamai/DataDome will block headless Playwright on
  some sites. Workaround: --headed mode or HAR export from real browser.
