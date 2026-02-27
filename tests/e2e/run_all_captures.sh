#!/usr/bin/env bash
# Run CaskMCP mint against multiple real ecommerce sites for E2E testing.
# Usage: ./tests/e2e/run_all_captures.sh [site_name]
# If site_name is provided, only that site is tested.
set -euo pipefail

VENV=".venv/bin/python"
CASKMCP="$VENV -m caskmcp.cli.main"

SITES=(
    "amazon:https://www.amazon.com:*.amazon.com,*.media-amazon.com"
    "stockx:https://stockx.com:*.stockx.com,*.stockx.io"
    "walmart:https://www.walmart.com:*.walmart.com,*.walmartimages.com"
    "tcgplayer:https://www.tcgplayer.com:*.tcgplayer.com"
    "target:https://www.target.com:*.target.com,*.targetimg.com"
    "ebay:https://www.ebay.com:*.ebay.com,*.ebaystatic.com"
)

TARGET_SITE="${1:-all}"
RESULTS_DIR="tests/e2e/results"
mkdir -p "$RESULTS_DIR"

for site_entry in "${SITES[@]}"; do
    IFS=':' read -r name url allowed <<< "$site_entry"

    if [ "$TARGET_SITE" != "all" ] && [ "$TARGET_SITE" != "$name" ]; then
        continue
    fi

    echo ""
    echo "=========================================="
    echo "  Minting: $name ($url)"
    echo "=========================================="

    SCRIPT="tests/e2e/${name}_capture.py"
    OUT_DIR="$RESULTS_DIR/$name"
    mkdir -p "$OUT_DIR"

    # Run mint with verbose output, capture both stdout and stderr
    $CASKMCP --verbose mint "$url" \
        -a "$allowed" \
        --scope first_party_only \
        --script "$SCRIPT" \
        2>&1 | tee "$OUT_DIR/mint_output.log" || {
            echo "WARN: $name mint failed or had errors"
            echo "FAILED" > "$OUT_DIR/status.txt"
            continue
        }

    echo "SUCCESS" > "$OUT_DIR/status.txt"

    # Find the most recent toolpack
    LATEST_TOOLPACK=$(ls -td .caskmcp/toolpacks/*/toolpack.yaml 2>/dev/null | head -1)
    if [ -n "$LATEST_TOOLPACK" ]; then
        TOOLPACK_DIR=$(dirname "$LATEST_TOOLPACK")
        cp -r "$TOOLPACK_DIR" "$OUT_DIR/toolpack_copy" 2>/dev/null || true

        # Copy key artifacts for analysis
        for artifact in tools.json baseline.json scopes.suggested.yaml; do
            src="$TOOLPACK_DIR/artifact/$artifact"
            [ -f "$src" ] && cp "$src" "$OUT_DIR/" 2>/dev/null || true
        done

        # Copy lockfile
        find "$TOOLPACK_DIR" -name "*.lock.pending.yaml" -exec cp {} "$OUT_DIR/" \; 2>/dev/null || true
    fi

    echo "  -> Output saved to $OUT_DIR/"
done

echo ""
echo "=========================================="
echo "  All captures complete."
echo "  Results: $RESULTS_DIR/"
echo "=========================================="
