#!/usr/bin/env bash
# scan_secrets.sh -- Scan toolwright artifacts for leaked secrets.
# Usage: scripts/scan_secrets.sh <dir1> [dir2] ...
# Exit 0 = clean, Exit 1 = secrets found.
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <dir1> [dir2] ..."
  exit 2
fi

PATTERNS=(
  'Authorization:'
  'Bearer [A-Za-z0-9._~+/=-]+'
  'Cookie:'
  'Set-Cookie:'
  'ghp_[A-Za-z0-9_]+'
  'github_pat_[A-Za-z0-9_]+'
  'gho_[A-Za-z0-9_]+'
  'x-api-key'
  'client_secret'
  'refresh_token'
  'access_token'
  'id_token'
  'private_key'
  'BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY'
)

# Build a combined regex from all patterns.
COMBINED=""
for p in "${PATTERNS[@]}"; do
  if [[ -n "$COMBINED" ]]; then
    COMBINED="${COMBINED}|${p}"
  else
    COMBINED="$p"
  fi
done

FOUND=0
for TARGET in "$@"; do
  if [[ ! -e "$TARGET" ]]; then
    echo "WARN: $TARGET does not exist, skipping"
    continue
  fi
  echo "Scanning: $TARGET"
  # Exclude binary files, .pyc, .whl, images, fonts.
  HITS=$(grep -rEi "$COMBINED" "$TARGET" \
    --include='*.json' --include='*.yaml' --include='*.yml' \
    --include='*.md' --include='*.txt' --include='*.jsonl' \
    --include='*.sh' --include='*.py' --include='*.toml' \
    --include='*.cfg' --include='*.ini' --include='*.env' \
    2>/dev/null || true)

  # Filter out known safe patterns:
  # - [REDACTED] values (toolwright already redacted them)
  # - Schema/model references (field names like "access_token" in JSON schemas)
  # - Test fixtures with placeholder values
  # - Policy rule references (e.g. "redact_fields: [authorization]")
  REAL_HITS=$(echo "$HITS" | grep -v '\[REDACTED\]' \
    | grep -v '"type":' \
    | grep -v '"description":' \
    | grep -v 'redact_fields' \
    | grep -v 'sensitive_headers' \
    | grep -v 'SENSITIVE_HEADERS' \
    | grep -v 'SENSITIVE_PARAMS' \
    | grep -v 'SENSITIVE_BODY_PATTERNS' \
    | grep -v 'redact_headers' \
    | grep -v 'redact_patterns' \
    | grep -v 'redact_pattern_justifications' \
    | grep -v '^.*policy\.yaml:- ' \
    | grep -v 'Redact ' \
    | grep -v '# ' \
    | grep -v 'pattern' \
    | grep -v 'def ' \
    | grep -v 'class ' \
    | grep -v 'import ' \
    | grep -v 'scan_secrets' \
    | grep -v 'test_' \
    | grep -v 'assert' \
    | grep -v '"name":' \
    | grep -v 'enum' \
    || true)

  if [[ -n "$REAL_HITS" ]]; then
    echo "SECRETS FOUND in $TARGET:"
    echo "$REAL_HITS"
    FOUND=1
  fi
done

if [[ $FOUND -eq 1 ]]; then
  echo ""
  echo "FAIL: Secrets detected in artifacts. See above."
  exit 1
else
  echo "PASS: No secrets found."
  exit 0
fi
