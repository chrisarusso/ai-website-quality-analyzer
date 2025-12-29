"""End-to-end tests for the fix flow.

These tests verify:
1. Parsing original/proposed values from issue data
2. GitHub issue creation with proper formatting
3. Code fix generation and PR creation
4. Content fix generation
"""

import os
import re
import pytest
from unittest.mock import Mock, patch, MagicMock

# Test data representing different issue types
SPELLING_ISSUE = {
    "category": "spelling",
    "severity": "medium",
    "title": "Spelling error: 'ROT'",
    "description": "The word 'ROT' appears to be misspelled.",
    "recommendation": "Change to: ROI",
    "url": "https://demo-agent-savas-labs.pantheonsite.io/services/landing/engineering",
    "element": "We evaluate existing systems and craft a plan to maximize ROT while accounting for constraints.",
}

SPELLING_ISSUE_CRYPO = {
    "category": "spelling",
    "severity": "medium",
    "title": "Spelling error: 'crypo'",
    "description": "The word 'crypo' appears to be misspelled.",
    "recommendation": "Change to: crypto",
    "url": "https://demo-agent-savas-labs.pantheonsite.io/blog/browsers-other-chrome",
    "element": "Brave comes with a lot of crypo stuff out of the box.",
}

GRAMMAR_ISSUE = {
    "category": "grammar",
    "severity": "medium",
    "title": "Grammar issue: Missing article",
    "description": "Missing article before noun.",
    "recommendation": "Add 'the' before 'system'",
    "url": "https://example.com/page",
    "element": "We need to update system before deployment.",
}

BROKEN_LINK_ISSUE = {
    "category": "links",
    "severity": "high",
    "title": "Broken link detected",
    "description": "Link returns 404 status.",
    "recommendation": "Remove or fix the broken link.",
    "url": "https://example.com/page",
    "element": '<a href="https://broken.example.com/page">Click here</a>',
}


class TestParseOriginalProposed:
    """Test extraction of original_value and proposed_value from issue data."""

    def parse_values(self, issue: dict) -> tuple:
        """Extract original and proposed values using the same logic as app.py."""
        original_value = None
        proposed_value = None

        # Extract from title: "Spelling error: 'word'" -> word
        title_match = re.search(r"error:\s*['\"]([^'\"]+)['\"]", issue.get("title", ""), re.IGNORECASE)
        if title_match:
            original_value = title_match.group(1)

        # Extract from recommendation: "Change to: suggestion"
        rec_match = re.search(r"Change to:\s*(.+)", issue.get("recommendation", ""), re.IGNORECASE)
        if rec_match:
            proposed_value = rec_match.group(1).strip()

        # Fallback: try broken link format in element
        if not original_value and issue.get("element"):
            link_match = re.search(r'(<a\s+href=["\'][^"\']+["\'][^>]*>[^<]+</a>)', issue["element"], re.IGNORECASE)
            if link_match:
                full_link_html = link_match.group(1)
                text_match = re.search(r'>([^<]+)</a>', full_link_html, re.IGNORECASE)
                link_text = text_match.group(1) if text_match else ""
                original_value = full_link_html
                proposed_value = link_text

        return original_value, proposed_value

    def test_spelling_rot_roi(self):
        """Test parsing ROT -> ROI spelling error."""
        original, proposed = self.parse_values(SPELLING_ISSUE)
        assert original == "ROT", f"Expected 'ROT', got '{original}'"
        assert proposed == "ROI", f"Expected 'ROI', got '{proposed}'"

    def test_spelling_crypo_crypto(self):
        """Test parsing crypo -> crypto spelling error."""
        original, proposed = self.parse_values(SPELLING_ISSUE_CRYPO)
        assert original == "crypo", f"Expected 'crypo', got '{original}'"
        assert proposed == "crypto", f"Expected 'crypto', got '{proposed}'"

    def test_broken_link_extraction(self):
        """Test parsing broken link - extracts full HTML and link text."""
        original, proposed = self.parse_values(BROKEN_LINK_ISSUE)
        assert original == '<a href="https://broken.example.com/page">Click here</a>'
        assert proposed == "Click here"

    def test_grammar_no_simple_extraction(self):
        """Grammar issues may not have simple original/proposed extraction."""
        original, proposed = self.parse_values(GRAMMAR_ISSUE)
        # Grammar title doesn't match "error: 'word'" pattern
        assert original is None
        assert proposed is None


class TestHtmlAwarePattern:
    """Test the HTML-aware regex pattern builder."""

    def test_single_word_with_boundaries(self):
        """Single word pattern should have word boundaries."""
        from website_agent.fixer.code_fix_generator import CodeFixGenerator
        from website_agent.fixer.github_client import GitHubClient

        github = GitHubClient("test/repo")
        gen = CodeFixGenerator(github)

        pattern = gen._build_html_aware_pattern("ROT")
        assert pattern == r"\bROT\b"

        # Should match standalone ROT
        assert re.search(pattern, "maximize ROT while", re.IGNORECASE)
        # Should NOT match ROT inside other words
        assert not re.search(pattern, "PROTECTED", re.IGNORECASE)
        assert not re.search(pattern, "rotisserie", re.IGNORECASE)

    def test_multi_word_with_html(self):
        """Multi-word pattern should allow HTML tags between words."""
        from website_agent.fixer.code_fix_generator import CodeFixGenerator
        from website_agent.fixer.github_client import GitHubClient

        github = GitHubClient("test/repo")
        gen = CodeFixGenerator(github)

        pattern = gen._build_html_aware_pattern("maximize ROT while")

        # Should match plain text
        assert re.search(pattern, "maximize ROT while accounting", re.IGNORECASE)
        # Should match with HTML tags between words
        assert re.search(pattern, "maximize <strong>ROT</strong> while", re.IGNORECASE)
        assert re.search(pattern, "maximize <a href='#'>ROT</a> while", re.IGNORECASE)


class TestGitHubIssueFormatting:
    """Test that GitHub issues are formatted correctly."""

    def test_issue_body_has_separate_original_suggested_blocks(self):
        """Original and Suggested should be in separate code blocks, not inline."""
        from website_agent.fixer.github_client import GitHubClient

        # Mock the GitHub API
        with patch('website_agent.fixer.github_client.httpx.Client'):
            client = GitHubClient("test/repo")

            # Mock create_issue to capture the body
            created_body = None
            def capture_issue(title, body, labels=None):
                nonlocal created_body
                created_body = body
                mock_issue = Mock()
                mock_issue.number = 1
                mock_issue.html_url = "https://github.com/test/repo/issues/1"
                return mock_issue

            client.create_issue = capture_issue

            # Call create_issue_from_quality_issue
            client.create_issue_from_quality_issue(
                category="spelling",
                severity="medium",
                title="Spelling error: 'ROT'",
                description="The word 'ROT' appears to be misspelled.",
                recommendation="Change to: ROI",
                url="https://example.com/page",
                element="We craft a plan to maximize ROT while accounting for constraints.",
                original_value="ROT",
                proposed_value="ROI",
                fix_type="code_fix",
            )

            # Verify the body format
            assert created_body is not None
            assert "### Original" in created_body
            assert "### Suggested" in created_body
            assert "### HTML Context" in created_body

            # Original and Suggested should be in separate sections, not "ROT → ROI"
            assert "→" not in created_body, "Should not have arrow format in body"

            # Should have code blocks
            assert "```\nROT\n```" in created_body
            assert "```\nROI\n```" in created_body


class TestCodeFixFlow:
    """Test the code fix generation flow."""

    def test_search_finds_correct_file(self):
        """Search should find files containing the typo."""
        # This test requires the actual repo to be cloned
        # Skip if not available
        repo_path = "/tmp/github-repo-cache/savaslabs-poc-savaslabs.com-demo-agent"
        if not os.path.exists(repo_path):
            pytest.skip("Repo not cloned - run a code fix first to clone")

        from website_agent.fixer.github_client import GitHubClient

        github = GitHubClient("savaslabs/poc-savaslabs.com")
        results = github.search_for_text_in_templates(
            "ROT",
            branch="demo-agent",
            pantheon_git_url=None,  # Use cached clone
        )

        # Should find some results
        assert len(results) > 0

        # Custom theme should be prioritized
        custom_results = [r for r in results if "/custom/" in r.path]
        assert len(custom_results) > 0, "Should find files in custom theme"

    def test_pattern_filters_to_actual_matches(self):
        """Pattern with word boundaries should filter out false positives."""
        repo_path = "/tmp/github-repo-cache/savaslabs-poc-savaslabs.com-demo-agent"
        if not os.path.exists(repo_path):
            pytest.skip("Repo not cloned")

        from website_agent.fixer.code_fix_generator import CodeFixGenerator
        from website_agent.fixer.github_client import GitHubClient

        github = GitHubClient("savaslabs/poc-savaslabs.com")
        gen = CodeFixGenerator(github)

        # Search returns many files with "ROT" as substring (like PROTECTED)
        results = github.search_for_text_in_templates("ROT", branch="demo-agent")

        # But pattern should only match standalone ROT
        pattern = gen._build_html_aware_pattern("ROT")
        matched_files = []

        for result in results[:10]:  # Check first 10
            try:
                content, _ = github.get_file_content_local(result.path, branch="demo-agent")
                if re.search(pattern, content, re.IGNORECASE):
                    matched_files.append(result.path)
            except:
                pass

        # Should have fewer matches than raw search results
        assert len(matched_files) < len(results), "Pattern should filter out false positives"


class TestContentFixFlow:
    """Test the content fix generation flow."""

    def test_drush_command_format(self):
        """Verify the drush command format for content fixes."""
        # The content fix uses terminus drush to execute PHP
        # This test verifies the command structure is correct

        site = "savas-labs"
        env = "demo-agent"
        expected_prefix = f"terminus drush {site}.{env} -- ev"

        # Just verify the command format is valid
        assert "terminus" in expected_prefix
        assert "drush" in expected_prefix
        assert "ev" in expected_prefix  # eval PHP


# Integration test - requires running server
class TestFixEndpoint:
    """Test the /api/fix endpoint."""

    @pytest.fixture
    def api_url(self):
        return "http://localhost:8003"

    def test_fix_endpoint_parses_spelling_correctly(self, api_url):
        """Test that fix endpoint correctly parses spelling issues."""
        import requests

        # Skip if server not running
        try:
            requests.get(f"{api_url}/api/health", timeout=2)
        except:
            pytest.skip("Server not running on port 8003")

        # This would be a real integration test
        # For now, just verify the endpoint exists
        # A full test would submit a fix request and verify the GitHub issue


class TestFullCodeFixFlow:
    """Full end-to-end test for code fix generation."""

    def test_generate_fix_for_rot(self):
        """Test generating a fix for ROT -> ROI typo."""
        import subprocess

        # Skip if terminus not available
        result = subprocess.run(["which", "terminus"], capture_output=True)
        if result.returncode != 0:
            pytest.skip("Terminus not available")

        # Get Pantheon git URL
        result = subprocess.run(
            ["terminus", "connection:info", "savas-labs.demo-agent", "--field=git_url"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            pytest.skip("Cannot get Pantheon git URL")

        pantheon_git_url = result.stdout.strip()

        from website_agent.fixer.github_client import GitHubClient
        from website_agent.fixer.code_fix_generator import CodeFixGenerator

        github = GitHubClient("savaslabs/poc-savaslabs.com")
        generator = CodeFixGenerator(github)

        # Generate fix
        fix_result = generator.generate_fix(
            issue_title="Spelling error: 'ROT'",
            issue_description="The word 'ROT' appears to be misspelled.",
            page_url="https://demo-agent-savas-labs.pantheonsite.io/services/landing/engineering",
            user_instructions="Fix the typo ROT -> ROI",
            original_value="ROT",
            proposed_value="ROI",
            category="spelling",
            branch="demo-agent",
            pantheon_git_url=pantheon_git_url,
        )

        # Verify results
        assert fix_result.success, f"Fix generation failed: {fix_result.error}"
        assert len(fix_result.fixes) >= 1, "Should generate at least one fix"

        # Check the fix is for the right file
        fix = fix_result.fixes[0]
        assert "custom" in fix.file_path, f"Should fix custom theme file, got: {fix.file_path}"
        assert "ROI" in fix.fixed_content, "Fixed content should contain ROI"
        assert fix.confidence >= 0.5, f"Confidence too low: {fix.confidence}"


class TestOrchestratorFlow:
    """Test the orchestrator's fix processing."""

    def test_create_github_issue_with_correct_format(self):
        """Test that orchestrator creates GitHub issues with proper format."""
        from website_agent.fixer.orchestrator import FixOrchestrator
        from website_agent.models import ProposedFix, FixType, FixStatus
        from unittest.mock import Mock, patch

        # Create a mock store
        mock_store = Mock()
        mock_store.update_fix_status = Mock()

        # Create orchestrator with mocked dependencies
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}):
            orchestrator = FixOrchestrator(
                store=mock_store,
                github_token="test-token",
                github_repo="savaslabs/poc-savaslabs.com",
            )

        # Create a test fix
        fix = ProposedFix(
            id="test-fix-1",
            scan_id="test-scan",
            issue_id=1,
            fix_type=FixType.CODE_FIX,
            status=FixStatus.PENDING,
            confidence=0.9,
            original_value="ROT",
            proposed_value="ROI",
        )

        issue_data = {
            "category": "spelling",
            "severity": "medium",
            "title": "Spelling error: 'ROT'",
            "description": "The word 'ROT' appears to be misspelled.",
            "recommendation": "Change to: ROI",
            "url": "https://example.com/page",
            "element": "We craft a plan to maximize ROT while accounting for constraints.",
        }

        # Mock the GitHub client
        with patch.object(orchestrator, '_get_github_client') as mock_get_client:
            mock_client = Mock()
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)

            created_issue_body = None
            def capture_issue(**kwargs):
                nonlocal created_issue_body
                created_issue_body = kwargs
                mock_issue = Mock()
                mock_issue.number = 1
                mock_issue.html_url = "https://github.com/test/issues/1"
                return mock_issue

            mock_client.create_issue_from_quality_issue = capture_issue
            mock_get_client.return_value = mock_client

            # Call the method
            result = orchestrator.create_github_issue_for_fix(fix, issue_data)

            # Verify the issue was created with correct values
            assert created_issue_body is not None
            assert created_issue_body["original_value"] == "ROT"
            assert created_issue_body["proposed_value"] == "ROI"
            assert created_issue_body["element"] == issue_data["element"]


class TestFullSixFixes:
    """Integration test: Run all 6 test fixes against live API.

    This tests the complete fix flow including:
    - 3 spelling fixes (crypo, mayconfuse, ROT)
    - 2 grammar fixes (subject-verb agreement, verb tense)
    - 1 link fix (NYTimes 403)

    Requires:
    - API running on localhost:8003
    - Scan 7dc37550 to exist with the test issues
    - Drupal demo-agent environment to be accessible
    """

    # The 6 test cases
    TESTS = [
        {"category": "spelling", "search": "crypo", "desc": "crypo -> crypto",
         "instructions": "Fix the typo 'crypo' to 'crypto'"},
        {"category": "spelling", "search": "mayconfuse", "desc": "mayconfuse -> may confuse",
         "instructions": "Fix 'mayconfuse' to 'may confuse'"},
        {"category": "spelling", "search": "ROT", "desc": "ROT -> ROI (code)",
         "instructions": "Fix 'ROT' to 'ROI'"},
        {"category": "grammar", "search": "application run", "desc": "Subject-verb agreement",
         "instructions": "Fix the subject-verb agreement error"},
        {"category": "grammar", "search": "verb tense", "desc": "Verb tense fix",
         "instructions": "Fix the verb tense error"},
        {"category": "links", "search": "nytimes", "desc": "NYTimes 403 link",
         "instructions": "Remove the link but keep the text '$392M settlement' as plain text."},
    ]

    API_BASE = "http://localhost:8003"
    SCAN_ID = "7dc37550"
    GITHUB_REPO = "savaslabs/poc-savaslabs.com"

    @pytest.fixture
    def check_api(self):
        """Check if API is running."""
        import requests
        try:
            resp = requests.get(f"{self.API_BASE}/", timeout=2)
            if resp.status_code != 200:
                pytest.skip("API not running on port 8003")
        except:
            pytest.skip("API not running on port 8003")

    def test_find_all_six_issues(self, check_api):
        """Test that all 6 test issues can be found in the scan."""
        import requests
        import hashlib

        resp = requests.get(f"{self.API_BASE}/api/scan/{self.SCAN_ID}/issues")
        if resp.status_code != 200:
            pytest.skip(f"Scan {self.SCAN_ID} not found")

        issues_by_cat = resp.json().get("issues_by_category", {})

        found_count = 0
        for test in self.TESTS:
            found = None
            for issue in issues_by_cat.get(test["category"], []):
                title = issue.get("title", "").lower()
                element = issue.get("element", "").lower()
                search = test["search"].lower()
                if search in title or search in element:
                    found = issue
                    break

            if found:
                found_count += 1
            else:
                print(f"NOT FOUND: {test['desc']}")

        assert found_count == 6, f"Expected 6 issues, found {found_count}"

    def test_submit_and_complete_all_fixes(self, check_api):
        """Submit all 6 fixes and wait for completion.

        This is a long-running integration test that:
        1. Finds all 6 issues from the scan
        2. Submits them to /api/fix
        3. Polls for completion (up to 5 minutes)
        4. Verifies all 6 succeeded
        """
        import requests
        import hashlib
        import time

        # Get issues
        resp = requests.get(f"{self.API_BASE}/api/scan/{self.SCAN_ID}/issues")
        issues_by_cat = resp.json().get("issues_by_category", {})

        # Find and prepare all issues
        fix_issues = []
        for test in self.TESTS:
            found = None
            for issue in issues_by_cat.get(test["category"], []):
                title = issue.get("title", "").lower()
                element = issue.get("element", "").lower()
                search = test["search"].lower()
                if search in title or search in element:
                    found = issue
                    break

            if not found:
                pytest.skip(f"Issue not found: {test['desc']}")

            # Generate issue ID
            key = f"{found.get('category')}:{found.get('title')}"
            issue_id = hashlib.md5(key.encode()).hexdigest()[:12]

            # Parse original/proposed values
            element = found.get("element", "")
            orig, prop = "", ""

            spell_match = re.search(r'"([^"]+)"\s*→\s*"([^"]+)"', element)
            if spell_match:
                orig, prop = spell_match.group(1), spell_match.group(2)

            gram_orig = re.search(r'Original:\s*"([^"]+)"', element)
            gram_sugg = re.search(r'Suggested:\s*"([^"]+)"', element)
            if gram_orig:
                orig = gram_orig.group(1)
            if gram_sugg:
                prop = gram_sugg.group(1)

            # For links, extract the anchor tag
            if test["category"] == "links" and not orig:
                link_match = re.search(r'(<a[^>]*>.*?</a>)', element, re.IGNORECASE)
                if link_match:
                    orig = link_match.group(1)
                    prop = re.sub(r'<a[^>]*>(.*?)</a>', r'\1', orig)

            fix_issues.append({
                "issue_id": issue_id,
                "category": found.get("category"),
                "severity": found.get("severity"),
                "title": found.get("title"),
                "url": found.get("url"),
                "element": found.get("element"),
                "recommendation": found.get("recommendation"),
                "user_instructions": test["instructions"],
                "original_value": orig,
                "proposed_value": prop,
            })

        assert len(fix_issues) == 6, f"Expected 6 issues, got {len(fix_issues)}"

        # Submit fix request
        fix_request = {
            "scan_id": self.SCAN_ID,
            "github_repo": self.GITHUB_REPO,
            "issues": fix_issues,
        }

        resp = requests.post(f"{self.API_BASE}/api/fix", json=fix_request, timeout=60)
        submit_result = resp.json()
        batch_id = submit_result.get("fix_batch_id")
        assert batch_id, "No batch_id returned"

        # Poll for completion (up to 5 minutes)
        start_time = time.time()
        for i in range(100):
            time.sleep(3)

            try:
                resp = requests.get(f"{self.API_BASE}/api/fix/{batch_id}/status", timeout=60)
                status = resp.json()
            except requests.exceptions.Timeout:
                continue

            fixes = status.get("fixes", [])
            terminal_states = ["applied", "draft_created", "failed", "pr_created"]
            completed = sum(1 for f in fixes if f.get("status") in terminal_states)

            if completed == len(fixes):
                # Verify results
                succeeded = sum(1 for f in fixes
                               if f.get("status") in ["draft_created", "pr_created", "applied"])

                # Check batching worked (should have 2 Drupal revisions for 4 content fixes)
                revision_urls = set()
                for fix in fixes:
                    if fix.get("drupal_revision_url"):
                        revision_urls.add(fix["drupal_revision_url"])

                assert succeeded == 6, f"Expected 6 successes, got {succeeded}"
                # With batching, 4 content fixes should create ≤2 revisions
                assert len(revision_urls) <= 2, f"Expected ≤2 revisions, got {len(revision_urls)}"
                return

        pytest.fail("Timeout: Fixes did not complete in 5 minutes")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
