#!/bin/bash
# validate_deployment.sh — Check prerequisites and deploy the Prior Authorization Assistant
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0

check_tool() {
    local tool="$1"
    local install_hint="$2"
    if command -v "$tool" &>/dev/null; then
        local version
        version=$("$tool" --version 2>&1 | head -1)
        echo -e "${GREEN}✓${NC} $tool found: $version"
    else
        echo -e "${RED}✗${NC} $tool not found. $install_hint"
        ERRORS=$((ERRORS + 1))
    fi
}

echo "============================================"
echo "Prior Authorization Assistant — Prerequisites"
echo "============================================"
echo ""

check_tool "aws"     "Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
check_tool "cdk"     "Install: npm install -g aws-cdk"
check_tool "python3" "Install: https://www.python.org/downloads/"
check_tool "node"    "Install: https://nodejs.org/"
check_tool "docker"  "Install: https://docs.docker.com/get-docker/"

echo ""

# Check AWS credentials
echo "Checking AWS credentials..."
if aws sts get-caller-identity &>/dev/null; then
    ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")
    echo -e "${GREEN}✓${NC} AWS credentials configured (account: $ACCOUNT, region: $REGION)"
else
    echo -e "${RED}✗${NC} AWS credentials not configured. Run: aws configure"
    ERRORS=$((ERRORS + 1))
fi

echo ""

if [ "$ERRORS" -gt 0 ]; then
    echo -e "${RED}$ERRORS prerequisite(s) missing. Fix the issues above before deploying.${NC}"
    exit 1
fi

echo -e "${GREEN}All prerequisites met.${NC}"


# ---------------------------------------------------------------------------
# Cleanup function (run with --cleanup flag)
# ---------------------------------------------------------------------------
cleanup() {
    echo ""
    echo "============================================"
    echo "Cleanup — Remove all deployed resources"
    echo "============================================"
    echo ""
    echo -e "${YELLOW}This will destroy ALL resources created by the CDK stack.${NC}"
    echo "Make sure you have downloaded any data you need from S3 buckets."
    echo ""
    read -p "Are you sure you want to proceed? (y/N) " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        echo "Running cdk destroy..."
        cd infrastructure
        cdk destroy --force
        echo -e "${GREEN}Cleanup complete. All resources removed.${NC}"
    else
        echo "Cleanup cancelled."
    fi
}

if [[ "${1:-}" == "--cleanup" ]]; then
    cleanup
    exit 0
fi

echo ""
echo "To deploy:  cd infrastructure && cdk deploy"
echo "To cleanup: bash scripts/validate_deployment.sh --cleanup"
