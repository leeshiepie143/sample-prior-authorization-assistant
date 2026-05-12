#!/bin/bash
# run_ash_scan.sh — Wrapper for Automated Security Helper (ASH) scanning
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ASH_DIR="${PROJECT_DIR}/.ash"
RESULTS_DIR="${PROJECT_DIR}/ash-results"

echo "============================================"
echo "ASH Security Scan — Prior Authorization Assistant"
echo "============================================"
echo ""

# Check Docker is running
if ! docker info &>/dev/null; then
    echo -e "${RED}✗ Docker is not running. ASH requires Docker.${NC}"
    exit 1
fi

# Clone ASH if not present
if [ ! -d "$ASH_DIR" ]; then
    echo "Cloning Automated Security Helper..."
    git clone https://github.com/awslabs/automated-security-helper.git "$ASH_DIR"
else
    echo -e "${GREEN}✓${NC} ASH already cloned at $ASH_DIR"
fi

# Clean previous results
rm -rf "$RESULTS_DIR"
mkdir -p "$RESULTS_DIR"

echo ""
echo "Running ASH scan (this may take several minutes)..."
echo ""

# Run ASH
bash "${ASH_DIR}/ash" --source-dir "$PROJECT_DIR" --output-dir "$RESULTS_DIR"

echo ""
echo "============================================"
echo "Scan Results Summary"
echo "============================================"
echo ""

# Parse results
TOTAL_ISSUES=0

for result_file in "$RESULTS_DIR"/*; do
    [ -f "$result_file" ] || continue
    filename=$(basename "$result_file")
    count=$(wc -l < "$result_file" 2>/dev/null || echo "0")
    count=$(echo "$count" | tr -d ' ')

    if [ "$count" -gt 0 ]; then
        echo -e "${YELLOW}⚠${NC}  $filename: $count line(s)"
        TOTAL_ISSUES=$((TOTAL_ISSUES + count))
    else
        echo -e "${GREEN}✓${NC}  $filename: clean"
    fi
done

echo ""
if [ "$TOTAL_ISSUES" -gt 0 ]; then
    echo -e "${YELLOW}Total issues found: $TOTAL_ISSUES${NC}"
    echo "Review results in: $RESULTS_DIR/"
    exit 1
else
    echo -e "${GREEN}No issues found. Repository is ready for CSR submission.${NC}"
fi
