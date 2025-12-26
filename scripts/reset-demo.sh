#!/bin/bash
# Reset script for demo environment
#
# This script:
# 1. Clears local fix records from the database
# 2. Optionally closes GitHub issues created for testing
# 3. Optionally syncs multidev from production (Platform.sh/Pantheon)
#
# Usage:
#   ./scripts/reset-demo.sh                    # Just clear local fix records
#   ./scripts/reset-demo.sh --close-issues     # Also close GitHub issues
#   ./scripts/reset-demo.sh --sync-multidev    # Also sync multidev from prod

set -e

cd "$(dirname "$0")/.."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Demo Environment Reset ===${NC}"

# Parse arguments
CLOSE_ISSUES=false
SYNC_MULTIDEV=false
MULTIDEV_NAME="quality-fix-test"

for arg in "$@"; do
    case $arg in
        --close-issues)
            CLOSE_ISSUES=true
            shift
            ;;
        --sync-multidev)
            SYNC_MULTIDEV=true
            shift
            ;;
        --multidev=*)
            MULTIDEV_NAME="${arg#*=}"
            shift
            ;;
        *)
            ;;
    esac
done

# 1. Clear fix records from local database
echo -e "\n${GREEN}1. Clearing fix records from local database...${NC}"
if [ -f "data/website_agent.db" ]; then
    sqlite3 data/website_agent.db "DELETE FROM proposed_fixes;"
    echo "   Cleared proposed_fixes table"

    # Show remaining record counts
    SCAN_COUNT=$(sqlite3 data/website_agent.db "SELECT COUNT(*) FROM scans;")
    ISSUE_COUNT=$(sqlite3 data/website_agent.db "SELECT COUNT(*) FROM issues;")
    echo "   Remaining: ${SCAN_COUNT} scans, ${ISSUE_COUNT} issues"
else
    echo "   No database found at data/website_agent.db"
fi

# 2. Optionally close GitHub issues
if [ "$CLOSE_ISSUES" = true ]; then
    echo -e "\n${GREEN}2. Closing GitHub issues with 'website-quality' label...${NC}"

    # Check if gh CLI is available
    if ! command -v gh &> /dev/null; then
        echo -e "   ${RED}GitHub CLI (gh) not installed. Skipping.${NC}"
    else
        REPO="${GITHUB_DEFAULT_REPO:-savaslabs/savaslabs.com}"
        echo "   Repo: $REPO"

        # List open issues with the website-quality label
        ISSUES=$(gh issue list --repo "$REPO" --label "website-quality" --state open --json number --jq '.[].number' 2>/dev/null || echo "")

        if [ -z "$ISSUES" ]; then
            echo "   No open issues with 'website-quality' label found"
        else
            COUNT=$(echo "$ISSUES" | wc -l | tr -d ' ')
            echo "   Found $COUNT open issue(s)"

            for issue_num in $ISSUES; do
                echo "   Closing issue #$issue_num..."
                gh issue close "$issue_num" --repo "$REPO" --comment "Closed by demo reset script" 2>/dev/null || echo "   Failed to close #$issue_num"
            done
        fi

        # Also close any PRs with fix/ prefix
        echo "   Checking for fix PRs..."
        PRS=$(gh pr list --repo "$REPO" --state open --json number,headRefName --jq '.[] | select(.headRefName | startswith("fix/website-quality")) | .number' 2>/dev/null || echo "")

        if [ -z "$PRS" ]; then
            echo "   No open fix PRs found"
        else
            for pr_num in $PRS; do
                echo "   Closing PR #$pr_num..."
                gh pr close "$pr_num" --repo "$REPO" --delete-branch 2>/dev/null || echo "   Failed to close PR #$pr_num"
            done
        fi
    fi
else
    echo -e "\n${YELLOW}2. Skipping GitHub issue cleanup (use --close-issues to enable)${NC}"
fi

# 3. Optionally sync multidev from production
if [ "$SYNC_MULTIDEV" = true ]; then
    echo -e "\n${GREEN}3. Syncing multidev from production...${NC}"

    # Check for Platform.sh CLI
    if command -v platform &> /dev/null; then
        echo "   Using Platform.sh CLI"
        echo "   Creating/syncing environment: $MULTIDEV_NAME"

        # Sync database from production
        # Note: Adjust project ID and environment names as needed
        platform db:dump -e main -y 2>/dev/null | platform db:sql -e "$MULTIDEV_NAME" 2>/dev/null || {
            echo -e "   ${YELLOW}Platform.sh sync failed - may need manual setup${NC}"
        }

    # Check for Terminus (Pantheon)
    elif command -v terminus &> /dev/null; then
        echo "   Using Terminus (Pantheon) CLI"
        SITE="${PANTHEON_SITE:-savaslabs}"

        # Check if multidev exists, create if not
        if ! terminus multidev:list "$SITE" --format=list 2>/dev/null | grep -q "$MULTIDEV_NAME"; then
            echo "   Creating multidev: $MULTIDEV_NAME"
            terminus multidev:create "$SITE".live "$MULTIDEV_NAME" 2>/dev/null || echo "   Failed to create multidev"
        fi

        # Sync database from live
        echo "   Syncing database from live to $MULTIDEV_NAME..."
        terminus env:clone-content "$SITE".live "$MULTIDEV_NAME" --db-only -y 2>/dev/null || {
            echo -e "   ${YELLOW}Terminus sync failed - may need manual setup${NC}"
        }

    else
        echo -e "   ${YELLOW}No Platform.sh or Pantheon CLI found.${NC}"
        echo "   To sync manually:"
        echo "   - Platform.sh: platform db:dump -e main | platform db:sql -e $MULTIDEV_NAME"
        echo "   - Pantheon: terminus env:clone-content site.live $MULTIDEV_NAME --db-only"
    fi
else
    echo -e "\n${YELLOW}3. Skipping multidev sync (use --sync-multidev to enable)${NC}"
fi

echo -e "\n${GREEN}=== Reset Complete ===${NC}"
echo ""
echo "Next steps:"
echo "  1. Run: uv run python scripts/regenerate-report.py"
echo "  2. Select 2-3 issues from the report"
echo "  3. Click 'Run Fixes' to test the workflow"
echo ""
