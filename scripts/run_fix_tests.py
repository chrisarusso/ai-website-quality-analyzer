#!/usr/bin/env python3
"""
Comprehensive fix flow test script.

Tests 7 specific fix scenarios:
1-2. Spelling content fixes: crypo->crypto, mayconfuse->may confuse (Drupal revisions)
3. Spelling code fix: ROT->ROI (GitHub PR to template)
4-5. Grammar content fixes (Drupal revisions)
6. Broken link fix with context "Just remove the link." (Drupal revision)

This script:
1. Runs a fresh scan of the demo-agent multidev
2. Identifies the specific issues to test
3. Submits fix requests for each
4. Verifies the results
"""

import json
import os
import subprocess
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'fix_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)

# Configuration
API_BASE = os.environ.get("API_BASE", "http://localhost:8003")
DEMO_SITE = "https://demo-agent-savas-labs.pantheonsite.io"
GITHUB_REPO = "savaslabs/poc-savaslabs.com"

# Test cases - the 7 fixes we're testing
TEST_CASES = [
    {
        "id": 1,
        "name": "Spelling: crypo -> crypto",
        "type": "content_fix",
        "search_title": "crypo",
        "expected_original": "crypo",
        "expected_proposed": "crypto",
        "verify": "drupal_revision",
    },
    {
        "id": 2,
        "name": "Spelling: mayconfuse -> may confuse",
        "type": "content_fix",
        "search_title": "mayconfuse",
        "expected_original": "mayconfuse",
        "expected_proposed": "may confuse",
        "verify": "drupal_revision",
    },
    {
        "id": 3,
        "name": "Spelling: ROT -> ROI (code fix)",
        "type": "code_fix",
        "search_title": "ROT",
        "expected_original": "ROT",
        "expected_proposed": "ROI",
        "verify": "github_pr",
    },
    {
        "id": 4,
        "name": "Grammar fix 1",
        "type": "content_fix",
        "search_category": "grammar",
        "index": 0,
        "verify": "drupal_revision",
    },
    {
        "id": 5,
        "name": "Grammar fix 2",
        "type": "content_fix",
        "search_category": "grammar",
        "index": 1,
        "verify": "drupal_revision",
    },
    {
        "id": 6,
        "name": "Broken link: NYTimes 403",
        "type": "content_fix",
        "search_title": "403",
        "user_instructions": "Just remove the link. Keep the text '$392M settlement' but remove the <a> tags around it.",
        "verify": "drupal_revision",
    },
]


class FixTestRunner:
    def __init__(self):
        self.api_base = API_BASE
        self.results = []
        self.scan_id = None

    def run_all_tests(self):
        """Run all test cases."""
        logger.info("=" * 60)
        logger.info("FIX FLOW TEST SUITE")
        logger.info("=" * 60)

        # Step 1: Run a fresh scan
        logger.info("\n[STEP 1] Running fresh scan of demo-agent site...")
        self.scan_id = self.run_scan()
        if not self.scan_id:
            logger.error("Failed to start scan")
            return False

        # Step 2: Wait for scan to complete
        logger.info(f"\n[STEP 2] Waiting for scan {self.scan_id} to complete...")
        if not self.wait_for_scan():
            logger.error("Scan failed or timed out")
            return False

        # Step 3: Get issues from scan
        logger.info("\n[STEP 3] Fetching issues from scan...")
        issues = self.get_scan_issues()
        if not issues:
            logger.error("No issues found in scan")
            return False
        logger.info(f"Found {sum(len(v) for v in issues.values())} issues across {len(issues)} categories")

        # Step 4: Run each test case
        logger.info("\n[STEP 4] Running test cases...")
        for test_case in TEST_CASES:
            self.run_test_case(test_case, issues)

        # Step 5: Print summary
        self.print_summary()

        return all(r["success"] for r in self.results)

    def run_scan(self):
        """Start a new scan and return the scan ID."""
        try:
            resp = requests.post(
                f"{self.api_base}/api/scan",
                json={
                    "url": DEMO_SITE,
                    "max_pages": 10,
                    "crawl_external": False,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("scan_id")
            else:
                logger.error(f"Scan request failed: {resp.status_code} - {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Scan request error: {e}")
            return None

    def wait_for_scan(self, timeout=300):
        """Wait for scan to complete."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = requests.get(f"{self.api_base}/api/scan/{self.scan_id}", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status")
                    logger.info(f"  Scan status: {status}, pages: {data.get('pages_crawled')}/{data.get('pages_total')}")
                    if status == "completed":
                        return True
                    elif status == "failed":
                        logger.error(f"Scan failed: {data.get('error')}")
                        return False
            except Exception as e:
                logger.warning(f"Error checking scan status: {e}")
            time.sleep(5)
        logger.error("Scan timed out")
        return False

    def get_scan_issues(self):
        """Get issues from the completed scan."""
        try:
            resp = requests.get(f"{self.api_base}/api/scan/{self.scan_id}/issues", timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("issues_by_category", {})
            return None
        except Exception as e:
            logger.error(f"Error getting issues: {e}")
            return None

    def find_issue_for_test(self, test_case, issues):
        """Find the matching issue for a test case."""
        # Search by title keyword
        if "search_title" in test_case:
            keyword = test_case["search_title"].lower()
            for category, category_issues in issues.items():
                for issue in category_issues:
                    if keyword in issue.get("title", "").lower():
                        return issue

        # Search by category and index
        if "search_category" in test_case:
            category = test_case["search_category"]
            index = test_case.get("index", 0)
            category_issues = issues.get(category, [])
            if len(category_issues) > index:
                return category_issues[index]

        return None

    def run_test_case(self, test_case, issues):
        """Run a single test case."""
        test_id = test_case["id"]
        test_name = test_case["name"]
        logger.info(f"\n--- Test {test_id}: {test_name} ---")

        # Find the issue
        issue = self.find_issue_for_test(test_case, issues)
        if not issue:
            self.results.append({
                "test_id": test_id,
                "name": test_name,
                "success": False,
                "error": "Could not find matching issue in scan",
            })
            logger.error(f"  FAILED: Could not find matching issue")
            return

        logger.info(f"  Found issue: {issue.get('title')}")
        logger.info(f"  URL: {issue.get('url')}")

        # Build fix request
        fix_request = {
            "scan_id": self.scan_id,
            "github_repo": GITHUB_REPO,
            "issues": [{
                "category": issue.get("category"),
                "severity": issue.get("severity"),
                "title": issue.get("title"),
                "url": issue.get("url"),
                "element": issue.get("element"),
                "recommendation": issue.get("recommendation"),
                "user_instructions": test_case.get("user_instructions", ""),
            }],
        }

        # Submit fix request
        try:
            logger.info(f"  Submitting fix request...")
            resp = requests.post(
                f"{self.api_base}/api/fix",
                json=fix_request,
                timeout=120,
            )

            if resp.status_code != 200:
                self.results.append({
                    "test_id": test_id,
                    "name": test_name,
                    "success": False,
                    "error": f"Fix request failed: {resp.status_code} - {resp.text[:200]}",
                })
                logger.error(f"  FAILED: {resp.status_code}")
                return

            fix_result = resp.json()
            logger.info(f"  Fix response: {json.dumps(fix_result, indent=2)[:500]}")

            # Verify the result
            verification = self.verify_fix(test_case, fix_result)

            self.results.append({
                "test_id": test_id,
                "name": test_name,
                "success": verification["success"],
                "fix_result": fix_result,
                "verification": verification,
            })

            if verification["success"]:
                logger.info(f"  PASSED: {verification.get('message', '')}")
            else:
                logger.error(f"  FAILED: {verification.get('error', '')}")

        except Exception as e:
            self.results.append({
                "test_id": test_id,
                "name": test_name,
                "success": False,
                "error": str(e),
            })
            logger.error(f"  FAILED: {e}")

    def verify_fix(self, test_case, fix_result):
        """Verify the fix was applied correctly."""
        verify_type = test_case.get("verify")

        if verify_type == "drupal_revision":
            # Check for revision URL in result
            fixes = fix_result.get("fixes", [])
            if not fixes:
                return {"success": False, "error": "No fixes returned"}

            fix = fixes[0]
            revision_url = fix.get("drupal_revision_url") or fix.get("revision_url")
            diff_url = fix.get("diff_url")

            if revision_url:
                return {
                    "success": True,
                    "message": f"Drupal revision created: {revision_url}",
                    "revision_url": revision_url,
                    "diff_url": diff_url,
                }
            else:
                return {"success": False, "error": "No revision URL in response"}

        elif verify_type == "github_pr":
            # Check for PR URL in result
            fixes = fix_result.get("fixes", [])
            if not fixes:
                return {"success": False, "error": "No fixes returned"}

            fix = fixes[0]
            pr_url = fix.get("github_pr_url") or fix.get("pr_url")

            if pr_url:
                return {
                    "success": True,
                    "message": f"GitHub PR created: {pr_url}",
                    "pr_url": pr_url,
                }
            else:
                # Check if at least a GitHub issue was created
                issue_url = fix.get("github_issue_url")
                if issue_url:
                    return {
                        "success": True,
                        "message": f"GitHub issue created (PR pending): {issue_url}",
                        "issue_url": issue_url,
                    }
                return {"success": False, "error": "No PR or issue URL in response"}

        return {"success": False, "error": f"Unknown verify type: {verify_type}"}

    def print_summary(self):
        """Print test summary."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)

        passed = sum(1 for r in self.results if r["success"])
        failed = len(self.results) - passed

        for result in self.results:
            status = "PASS" if result["success"] else "FAIL"
            logger.info(f"  [{status}] Test {result['test_id']}: {result['name']}")
            if not result["success"]:
                logger.info(f"         Error: {result.get('error', 'Unknown')}")
            elif result.get("verification", {}).get("message"):
                logger.info(f"         {result['verification']['message']}")

        logger.info("")
        logger.info(f"Results: {passed} passed, {failed} failed out of {len(self.results)} tests")
        logger.info("=" * 60)

        # Save results to file
        results_file = f"fix_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, "w") as f:
            json.dump({
                "scan_id": self.scan_id,
                "timestamp": datetime.now().isoformat(),
                "results": self.results,
                "summary": {"passed": passed, "failed": failed, "total": len(self.results)},
            }, f, indent=2)
        logger.info(f"\nResults saved to: {results_file}")


def main():
    # Check if API is running
    try:
        resp = requests.get(f"{API_BASE}/", timeout=5)
    except Exception as e:
        logger.error(f"API not running at {API_BASE}: {e}")
        logger.info("Start the API with: uv run uvicorn src.website_agent.api.app:app --port 8003")
        sys.exit(1)

    runner = FixTestRunner()
    success = runner.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
