#!/bin/bash
exec > quickstart-actual-output.md 2>&1

echo "# Quickstart Actual Output"
echo "# Captured: $(date)"
echo ""

echo "## toolwright --version"
toolwright --version
echo ""

echo "## Step 1: Install (already done)"
echo ""

echo "## Step 2: Mint"
echo '```'
echo "$ toolwright mint https://github.com -a api.github.com --duration 120"
echo '```'
echo ""
echo "(Interactive step — capture output manually, paste below)"
echo ""

echo "## Step 3: Auth check"
echo '```'
toolwright auth check
echo '```'
echo ""

echo "## Step 4: Gate status (before approval)"
echo '```'
toolwright gate status
echo '```'
echo ""

echo "## Step 4b: Gate allow"
echo '```'
toolwright gate allow --all --yes
echo '```'
echo ""

echo "## Step 4c: Gate status (after approval)"
echo '```'
toolwright gate status
echo '```'
echo ""

echo "## Step 5: Serve (startup output only)"
echo '```'
echo "$ toolwright serve --scope repos"
echo '```'
echo "(Copy the startup card output, then Ctrl-C)"
echo ""

echo "## Step 6: Config"
echo '```'
toolwright config
echo '```'
echo ""

echo "## Other useful outputs"
echo ""

echo "## groups list"
echo '```'
toolwright groups list
echo '```'
echo ""

echo "## status"
echo '```'
toolwright status
echo '```'
echo ""

echo "## rules template list"
echo '```'
toolwright rules template list
echo '```'
echo ""

echo "## recipes list"
echo '```'
toolwright recipes list
echo '```'