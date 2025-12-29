"""Fix orchestrator for processing website quality fixes.

Coordinates the fix process:
1. Creates GitHub issues for tracking
2. Processes CODE_FIX issues via GitHub PRs
3. Processes CONTENT_FIX issues via Drupal API
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _get_pantheon_git_url() -> Optional[str]:
    """Get the Pantheon git URL for the current site/env.

    Returns the git URL for cloning Pantheon code, or None if not available.
    """
    site = os.environ.get("PANTHEON_SITE")
    env = os.environ.get("PANTHEON_ENV", "dev")

    if not site:
        return None

    try:
        result = subprocess.run(
            ["terminus", "connection:info", f"{site}.{env}", "--field=git_url"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Could not get Pantheon git URL: {e}")

    return None

from ..models import FixStatus, FixType, ProposedFix
from ..storage import SQLiteStore
from .classifier import FixClassifier
from .code_fix_generator import CodeFixGenerator, CodeFixResult
from .content_fix_generator import ContentFixGenerator, generate_content_fix_sync
from .drupal_fixer import DrupalFixer, DrupalFixResult, fix_spelling_sync, fix_broken_link_sync, rollback_revision_sync
from .github_client import GitHubClient, GitHubClientError, GitHubIssue
from .run_tracker import get_tracker


@dataclass
class FixResult:
    """Result of processing a fix."""
    fix_id: str
    success: bool
    status: FixStatus
    message: str
    github_issue_url: Optional[str] = None
    github_issue_number: Optional[int] = None
    github_pr_url: Optional[str] = None
    drupal_revision_url: Optional[str] = None


class FixOrchestrator:
    """Orchestrates the fix process for website quality issues."""

    def __init__(
        self,
        store: Optional[SQLiteStore] = None,
        github_token: Optional[str] = None,
        github_repo: str = "savaslabs/savaslabs.com",
    ):
        """Initialize the orchestrator.

        Args:
            store: SQLite store for fix records
            github_token: GitHub personal access token
            github_repo: Repository in "owner/repo" format

        Drupal authentication is handled by the shared drupal-editor-agent library.
        Configure via environment variables:
        - PANTHEON_MACHINE_TOKEN + PANTHEON_SITE (for Terminus/Drush - preferred)
        - DRUPAL_BASE_URL + DRUPAL_USERNAME + DRUPAL_PASSWORD (for Playwright fallback)
        """
        self.store = store or SQLiteStore()
        self.classifier = FixClassifier()
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self.github_repo = github_repo

        # Check if Drupal fixing is available
        # Uses shared drupal-editor-agent with Terminus/Drush (preferred) or Playwright fallback
        self.drupal_available = bool(
            os.environ.get("PANTHEON_MACHINE_TOKEN") and os.environ.get("PANTHEON_SITE")
        ) or bool(
            os.environ.get("DRUPAL_BASE_URL") and os.environ.get("DRUPAL_USERNAME")
        )

    def _get_github_client(self, repo: Optional[str] = None) -> GitHubClient:
        """Get a GitHub client instance."""
        return GitHubClient(
            token=self.github_token,
            repo=repo or self.github_repo,
        )

    def create_github_issue_for_fix(
        self,
        fix: ProposedFix,
        issue_data: dict,
        github_repo: Optional[str] = None,
    ) -> FixResult:
        """Create a GitHub issue for a fix.

        Args:
            fix: The proposed fix record
            issue_data: Data about the original issue (title, description, etc.)
            github_repo: Repository to create issue in

        Returns:
            FixResult with the outcome
        """
        try:
            with self._get_github_client(github_repo) as client:
                gh_issue = client.create_issue_from_quality_issue(
                    category=issue_data.get("category", "unknown"),
                    severity=issue_data.get("severity", "medium"),
                    title=issue_data.get("title", "Unknown issue"),
                    description=issue_data.get("description", ""),
                    recommendation=issue_data.get("recommendation", ""),
                    url=issue_data.get("url", ""),
                    element=issue_data.get("element"),
                    user_instructions=fix.user_instructions,
                    fix_type=fix.fix_type.value if isinstance(fix.fix_type, FixType) else fix.fix_type,
                    original_value=fix.original_value,
                    proposed_value=fix.proposed_value,
                )

                # Update fix record with GitHub issue info
                self.store.update_fix_status(
                    fix.id,
                    status=FixStatus.PROCESSING,
                    github_issue_url=gh_issue.html_url,
                    github_issue_number=gh_issue.number,
                )

                return FixResult(
                    fix_id=fix.id,
                    success=True,
                    status=FixStatus.PROCESSING,
                    message=f"GitHub issue #{gh_issue.number} created",
                    github_issue_url=gh_issue.html_url,
                    github_issue_number=gh_issue.number,
                )

        except GitHubClientError as e:
            self.store.update_fix_status(
                fix.id,
                status=FixStatus.FAILED,
                error_message=str(e),
            )
            return FixResult(
                fix_id=fix.id,
                success=False,
                status=FixStatus.FAILED,
                message=f"Failed to create GitHub issue: {e}",
            )

    def process_code_fix(
        self,
        fix: ProposedFix,
        issue_data: dict,
        github_repo: Optional[str] = None,
    ) -> FixResult:
        """Process a CODE_FIX by searching the repo, generating a fix, and creating a PR.

        Uses LLM-powered CodeFixGenerator to:
        1. Search the repository for matching content
        2. Generate an intelligent fix based on issue + user instructions
        3. Create a PR with the fix

        Args:
            fix: The proposed fix record
            issue_data: Data about the original issue
            github_repo: Repository to create PR in

        Returns:
            FixResult with the outcome
        """
        # First create a GitHub issue if not already done
        if not fix.github_issue_url:
            issue_result = self.create_github_issue_for_fix(fix, issue_data, github_repo)
            if not issue_result.success:
                return issue_result

            # Update fix with issue info
            fix.github_issue_url = issue_result.github_issue_url
            fix.github_issue_number = issue_result.github_issue_number

        title = issue_data.get("title", "Unknown issue")

        # Determine branches for Pantheon multidev support
        # PANTHEON_ENV is used for CODE SEARCH (to find files in the multidev)
        # But PRs should target the GitHub default branch (master), not the multidev
        search_branch = os.environ.get("PANTHEON_ENV")
        if search_branch and search_branch == "live":
            search_branch = None

        # Get Pantheon git URL for multidev code search
        pantheon_git_url = _get_pantheon_git_url() if search_branch else None

        # PR base branch - use GITHUB_TARGET_BRANCH if configured
        # This should match the multidev branch if using Pantheon
        pr_base_branch = os.environ.get("GITHUB_TARGET_BRANCH")

        logger.info(f"Processing code fix for: {title} (search_branch: {search_branch or 'default'}, pr_base: {pr_base_branch or 'default'}, pantheon_git: {'yes' if pantheon_git_url else 'no'})")

        try:
            with self._get_github_client(github_repo) as client:
                # Use CodeFixGenerator to search repo and generate fix
                fix_generator = CodeFixGenerator(github_client=client)

                code_fix_result = fix_generator.generate_fix(
                    issue_title=title,
                    issue_description=issue_data.get("description", ""),
                    page_url=issue_data.get("url", ""),
                    user_instructions=fix.user_instructions or "",
                    original_value=fix.original_value,
                    proposed_value=fix.proposed_value,
                    category=issue_data.get("category", "unknown"),
                    branch=search_branch,  # Search in Pantheon multidev
                    pantheon_git_url=pantheon_git_url,  # Use Pantheon git for code search
                )

                if code_fix_result.success and code_fix_result.fix:
                    # Generate fix was successful - create the PR
                    generated_fix = code_fix_result.fix

                    # Create a branch for the fix from the PR base branch
                    branch_name = f"fix/website-quality-{fix.id}"
                    try:
                        client.create_branch(branch_name, from_branch=pr_base_branch)
                    except GitHubClientError as e:
                        if "Reference already exists" not in str(e):
                            raise

                    # Update the file with the fix
                    client.update_file(
                        path=generated_fix.file_path,
                        content=generated_fix.fixed_content,
                        message=f"fix: {title}\n\n{generated_fix.explanation}",
                        branch=branch_name,
                        sha=generated_fix.file_sha,
                    )

                    # Create the PR
                    pr_body_parts = [
                        "## Website Quality Fix",
                        "",
                        f"Fixes #{fix.github_issue_number}",
                        "",
                        f"**Issue:** {title}",
                        f"**File:** `{generated_fix.file_path}`",
                        f"**Confidence:** {generated_fix.confidence:.0%}",
                        "",
                        "### What Changed",
                        generated_fix.explanation,
                    ]

                    # Show original and suggested values as separate blocks
                    if fix.original_value or fix.proposed_value:
                        pr_body_parts.extend([
                            "",
                            "### Original",
                            "```",
                            fix.original_value or "(not specified)",
                            "```",
                            "",
                            "### Suggested",
                            "```",
                            fix.proposed_value or "(not specified)",
                            "```",
                        ])

                    if fix.user_instructions:
                        pr_body_parts.extend([
                            "",
                            "### User Instructions",
                            fix.user_instructions,
                        ])

                    # Add search context
                    if code_fix_result.search_results:
                        other_files = [
                            r.path for r in code_fix_result.search_results[1:4]
                            if r.path != generated_fix.file_path
                        ]
                        if other_files:
                            pr_body_parts.extend([
                                "",
                                "### Other Files Checked",
                                *[f"- `{p}`" for p in other_files],
                            ])

                    pr_body_parts.extend([
                        "",
                        "---",
                        "*Generated by Website Quality Agent using LLM-powered code analysis*",
                    ])

                    pr = client.create_pull_request(
                        title=f"[Fix] {title}",
                        body="\n".join(pr_body_parts),
                        head=branch_name,
                        base=pr_base_branch,  # Target GITHUB_TARGET_BRANCH (e.g., demo-agent)
                    )

                    # Update fix status
                    self.store.update_fix_status(
                        fix.id,
                        status=FixStatus.PR_CREATED,
                        github_pr_url=pr.html_url,
                    )

                    return FixResult(
                        fix_id=fix.id,
                        success=True,
                        status=FixStatus.PR_CREATED,
                        message=f"PR #{pr.number} created - {generated_fix.explanation}",
                        github_issue_url=fix.github_issue_url,
                        github_issue_number=fix.github_issue_number,
                        github_pr_url=pr.html_url,
                    )
                else:
                    # Could not generate fix - add context to GitHub issue
                    search_context = ""
                    if code_fix_result.search_results:
                        files_checked = [r.path for r in code_fix_result.search_results[:5]]
                        search_context = (
                            f"\n\n**Files checked:**\n"
                            + "\n".join(f"- `{p}`" for p in files_checked)
                        )

                    if fix.github_issue_number:
                        client.add_issue_comment(
                            fix.github_issue_number,
                            "⚠️ **Auto-fix not available**\n\n"
                            f"{code_fix_result.message}\n\n"
                            "This issue requires manual intervention. "
                            f"The automated fixer could not generate a fix.{search_context}\n\n"
                            f"*Processed on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
                        )

                    self.store.update_fix_status(
                        fix.id,
                        status=FixStatus.PROCESSING,
                        error_message=code_fix_result.error or "Auto-fix not available",
                    )

                    return FixResult(
                        fix_id=fix.id,
                        success=True,  # Issue created successfully
                        status=FixStatus.PROCESSING,
                        message=f"GitHub issue created, manual fix required: {code_fix_result.message}",
                        github_issue_url=fix.github_issue_url,
                        github_issue_number=fix.github_issue_number,
                    )

        except GitHubClientError as e:
            self.store.update_fix_status(
                fix.id,
                status=FixStatus.FAILED,
                error_message=str(e),
            )
            return FixResult(
                fix_id=fix.id,
                success=False,
                status=FixStatus.FAILED,
                message=f"Failed to create PR: {e}",
                github_issue_url=fix.github_issue_url,
                github_issue_number=fix.github_issue_number,
            )

    def _is_spelling_or_grammar_issue(self, issue_data: dict) -> bool:
        """Check if this is a spelling or grammar issue that can be auto-fixed."""
        category = issue_data.get("category", "").lower()
        return category in ("spelling", "grammar")

    def _is_broken_link_issue(self, issue_data: dict) -> bool:
        """Check if this is a broken link issue that can be auto-fixed."""
        category = issue_data.get("category", "").lower()
        title = issue_data.get("title", "").lower()
        # Only internal broken links can be fixed (remove or update)
        if category == "links":
            # External links are not fixable
            if "external" in title:
                return False
            # Any other broken/404/403 link is potentially fixable
            return "broken" in title or "404" in title or "403" in title
        return False

    def _search_code_for_text(
        self,
        search_text: str,
        github_repo: Optional[str] = None,
    ) -> bool:
        """Search the code repository for specific text.

        Args:
            search_text: The text to search for
            github_repo: Repository to search in

        Returns:
            True if text was found in code, False otherwise
        """
        if not search_text or len(search_text) < 3:
            return False

        logger.info(f"Searching code for: '{search_text}'")

        # Determine branches for Pantheon multidev support
        search_branch = os.environ.get("PANTHEON_ENV")
        if search_branch and search_branch == "live":
            search_branch = None

        pantheon_git_url = _get_pantheon_git_url() if search_branch else None

        try:
            with self._get_github_client(github_repo) as client:
                # Use the GitHub client's template search method directly
                search_results = client.search_for_text_in_templates(
                    text=search_text,
                    branch=search_branch,
                    pantheon_git_url=pantheon_git_url,
                )

                if search_results:
                    logger.info(f"Found '{search_text}' in code: {[r.path for r in search_results[:3]]}")
                    return True
                else:
                    logger.info(f"'{search_text}' not found in code, will try Drupal")
                    return False

        except Exception as e:
            logger.warning(f"Code search failed: {e}, will try Drupal")
            return False

    def process_content_fix(
        self,
        fix: ProposedFix,
        issue_data: dict,
        github_repo: Optional[str] = None,
    ) -> FixResult:
        """Process a CONTENT_FIX by first searching code, then Drupal.

        This method searches CODE FIRST before trying the database:
        1. Search for the text in the code repository (templates)
        2. If found in code, delegate to process_code_fix() for a PR
        3. If not found in code, try Drupal for a content revision

        Args:
            fix: The proposed fix record
            issue_data: Data about the original issue
            github_repo: Repository for GitHub issue tracking

        Returns:
            FixResult with the outcome
        """
        # STEP 1: Search CODE first before DATABASE
        # If the text is in a template, we need a code fix (PR), not a content fix
        search_text = fix.original_value
        if search_text and self._search_code_for_text(search_text, github_repo):
            logger.info(f"Text found in code - delegating to code fix: {search_text}")
            # Reclassify as CODE_FIX and delegate
            fix.fix_type = FixType.CODE_FIX
            return self.process_code_fix(fix, issue_data, github_repo)

        # STEP 2: Text not in code - proceed with Drupal content fix
        # First create a GitHub issue for tracking
        if not fix.github_issue_url:
            issue_result = self.create_github_issue_for_fix(fix, issue_data, github_repo)
            if not issue_result.success:
                return issue_result

            fix.github_issue_url = issue_result.github_issue_url
            fix.github_issue_number = issue_result.github_issue_number

        # Attempt LLM-powered content fix if Drupal is available
        drupal_revision_url = None
        drupal_diff_url = None
        drupal_fix_success = False
        drupal_fix_message = ""

        if self.drupal_available:
            page_url = issue_data.get("url", "")
            title = issue_data.get("title", "Unknown issue")

            # Use user instructions - this is key for LLM to understand what to do
            user_instructions = fix.user_instructions or ""

            # Add context from the issue
            if not user_instructions:
                # Build default instructions from issue data
                if fix.original_value and fix.proposed_value:
                    user_instructions = f"Change '{fix.original_value}' to '{fix.proposed_value}'"
                elif self._is_broken_link_issue(issue_data):
                    user_instructions = f"Fix or remove the broken link: {fix.original_value or 'see issue description'}"
                elif self._is_spelling_or_grammar_issue(issue_data):
                    user_instructions = f"Fix the spelling/grammar error"

            if page_url:
                logger.info(f"Generating LLM-powered content fix for: {title}")

                try:
                    # Use the LLM-powered content fix generator
                    result = generate_content_fix_sync(
                        page_url=page_url,
                        issue_title=title,
                        issue_description=issue_data.get("description", ""),
                        user_instructions=user_instructions,
                        category=issue_data.get("category", "unknown"),
                        original_value=fix.original_value,
                        proposed_value=fix.proposed_value,
                    )

                    if result.success:
                        drupal_fix_success = True
                        drupal_revision_url = result.revision_url
                        drupal_diff_url = result.diff_url
                        drupal_fix_message = result.message
                        # Note: Revision is in 'ava_suggestion' state, requires human approval
                    else:
                        drupal_fix_message = result.message or result.error
                        drupal_diff_url = None

                except Exception as e:
                    drupal_fix_message = f"Content fix error: {e}"
                    drupal_diff_url = None

        # Update GitHub issue with result
        try:
            with self._get_github_client(github_repo) as client:
                if fix.github_issue_number:
                    if drupal_fix_success and drupal_revision_url:
                        # Build comment with optional diff link
                        diff_section = ""
                        if drupal_diff_url:
                            diff_section = f"**View diff (compare changes):** {drupal_diff_url}\n\n"

                        # Drupal fix succeeded - revision is in 'ava_suggestion' state
                        client.add_issue_comment(
                            fix.github_issue_number,
                            "✅ **Drupal Draft Revision Created**\n\n"
                            f"{drupal_fix_message}\n\n"
                            f"**Review pending revision at:** {drupal_revision_url}\n\n"
                            f"{diff_section}"
                            "The fix has been applied as a draft revision in **`ava_suggestion`** state.\n"
                            "A human must review and approve the change before it goes live.\n\n"
                            "**To approve:** Open the revision URL above → Review → Approve & Publish\n\n"
                            f"*Processed on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
                        )

                        self.store.update_fix_status(
                            fix.id,
                            status=FixStatus.DRAFT_CREATED,
                            drupal_revision_url=drupal_revision_url,
                        )

                        return FixResult(
                            fix_id=fix.id,
                            success=True,
                            status=FixStatus.DRAFT_CREATED,
                            message=drupal_fix_message,
                            github_issue_url=fix.github_issue_url,
                            github_issue_number=fix.github_issue_number,
                            drupal_revision_url=drupal_revision_url,
                        )
                    else:
                        # Drupal fix failed or not applicable - manual fix required
                        comment_parts = ["📝 **Content Fix Required**\n"]

                        if drupal_fix_message:
                            comment_parts.append(f"Automated fix attempted: {drupal_fix_message}\n")

                        comment_parts.append(
                            "This is a content-level fix that needs to be made in the Drupal CMS.\n\n"
                            "**Steps:**\n"
                            "1. Log into the Drupal admin\n"
                            "2. Navigate to the content/media item\n"
                            "3. Make the required change\n"
                            "4. Save as draft for review\n\n"
                            f"*Processed on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
                        )

                        client.add_issue_comment(
                            fix.github_issue_number,
                            "\n".join(comment_parts),
                        )

            self.store.update_fix_status(
                fix.id,
                status=FixStatus.PROCESSING,
                error_message=drupal_fix_message or "Drupal integration pending - manual fix required",
            )

            return FixResult(
                fix_id=fix.id,
                success=True,
                status=FixStatus.PROCESSING,
                message=drupal_fix_message or "GitHub issue created, Drupal fix pending",
                github_issue_url=fix.github_issue_url,
                github_issue_number=fix.github_issue_number,
            )

        except GitHubClientError as e:
            return FixResult(
                fix_id=fix.id,
                success=True,  # Issue was created
                status=FixStatus.PROCESSING,
                message=f"GitHub issue created, but comment failed: {e}",
                github_issue_url=fix.github_issue_url,
                github_issue_number=fix.github_issue_number,
            )

    def process_fix(
        self,
        fix: ProposedFix,
        issue_data: dict,
        github_repo: Optional[str] = None,
    ) -> FixResult:
        """Process a single fix based on its type.

        Args:
            fix: The proposed fix record
            issue_data: Data about the original issue
            github_repo: Repository for GitHub operations

        Returns:
            FixResult with the outcome
        """
        fix_type = fix.fix_type
        if isinstance(fix_type, str):
            fix_type = FixType(fix_type)

        if fix_type == FixType.CODE_FIX:
            return self.process_code_fix(fix, issue_data, github_repo)
        elif fix_type == FixType.CONTENT_FIX:
            return self.process_content_fix(fix, issue_data, github_repo)
        elif fix_type == FixType.MANUAL_ONLY:
            # Just create a GitHub issue for tracking
            return self.create_github_issue_for_fix(fix, issue_data, github_repo)
        else:
            # NOT_FIXABLE - just create an issue for awareness
            return self.create_github_issue_for_fix(fix, issue_data, github_repo)

    def process_batch(
        self,
        batch_id: str,
        issue_data_map: dict[str, dict],
        github_repo: Optional[str] = None,
    ) -> list[FixResult]:
        """Process all fixes in a batch.

        Content fixes are grouped by target URL so multiple fixes on the same
        node are applied in a single Drupal revision. This prevents multiple
        revisions for the same node when batch contains several related fixes.

        Automatically tracks changes for rollback capability.

        Args:
            batch_id: The batch ID to process
            issue_data_map: Map of fix_id -> issue data
            github_repo: Repository for GitHub operations

        Returns:
            List of FixResult for each fix
        """
        # Start tracking this run for rollback
        tracker = get_tracker()
        run_id = tracker.start_run(run_id=batch_id)
        logger.info(f"Started fix run: {run_id}")

        fixes = self.store.get_fixes_by_batch(batch_id)
        results = []

        # Separate content fixes from other types for batching by node
        content_fixes_by_url: dict[str, list[tuple[ProposedFix, dict]]] = {}
        other_fixes: list[tuple[ProposedFix, dict]] = []

        for fix in fixes:
            issue_data = issue_data_map.get(fix.id, {})
            fix_type = fix.fix_type
            if isinstance(fix_type, str):
                fix_type = FixType(fix_type)

            if fix_type == FixType.CONTENT_FIX:
                # Group content fixes by their target URL
                page_url = issue_data.get("url", "")
                if page_url:
                    if page_url not in content_fixes_by_url:
                        content_fixes_by_url[page_url] = []
                    content_fixes_by_url[page_url].append((fix, issue_data))
                else:
                    # No URL - process individually
                    other_fixes.append((fix, issue_data))
            else:
                # CODE_FIX, MANUAL_ONLY, NOT_FIXABLE - process individually
                other_fixes.append((fix, issue_data))

        # Process grouped content fixes by URL (one revision per node)
        for page_url, fix_list in content_fixes_by_url.items():
            if len(fix_list) == 1:
                # Single fix - use normal processing
                fix, issue_data = fix_list[0]
                result = self.process_content_fix(fix, issue_data, github_repo)
                results.append(result)
            else:
                # Multiple fixes for same URL - batch them
                logger.info(f"Batching {len(fix_list)} content fixes for {page_url}")
                batch_results = self.process_content_fixes_batched(
                    fix_list, page_url, github_repo
                )
                results.extend(batch_results)

        # Process other fixes individually
        for fix, issue_data in other_fixes:
            result = self.process_fix(fix, issue_data, github_repo)
            results.append(result)

        # End the run and save to disk
        run_file = tracker.end_run()
        logger.info(f"Fix run saved to: {run_file}")

        return results

    def process_content_fixes_batched(
        self,
        fix_list: list[tuple[ProposedFix, dict]],
        page_url: str,
        github_repo: Optional[str] = None,
    ) -> list[FixResult]:
        """Process multiple content fixes for the same node in one revision.

        All fixes targeting the same page URL are applied together, creating
        a single Drupal revision with all changes.

        Args:
            fix_list: List of (ProposedFix, issue_data) tuples for the same URL
            page_url: The target page URL
            github_repo: Repository for GitHub issue tracking

        Returns:
            List of FixResult for each fix
        """
        results = []

        # First, check if any of these fixes should actually be code fixes
        # by searching for their text in the codebase
        content_fixes = []
        for fix, issue_data in fix_list:
            search_text = fix.original_value
            if search_text and self._search_code_for_text(search_text, github_repo):
                logger.info(f"Text found in code - delegating to code fix: {search_text}")
                fix.fix_type = FixType.CODE_FIX
                result = self.process_code_fix(fix, issue_data, github_repo)
                results.append(result)
            else:
                content_fixes.append((fix, issue_data))

        # If no content fixes remain, we're done
        if not content_fixes:
            return results

        # Create GitHub issues for all remaining content fixes
        for fix, issue_data in content_fixes:
            if not fix.github_issue_url:
                issue_result = self.create_github_issue_for_fix(fix, issue_data, github_repo)
                if issue_result.success:
                    fix.github_issue_url = issue_result.github_issue_url
                    fix.github_issue_number = issue_result.github_issue_number

        # Attempt batched Drupal fix if available
        if not self.drupal_available:
            # No Drupal - return processing status for all
            for fix, issue_data in content_fixes:
                self.store.update_fix_status(
                    fix.id,
                    status=FixStatus.PROCESSING,
                    error_message="Drupal integration pending - manual fix required",
                )
                results.append(FixResult(
                    fix_id=fix.id,
                    success=True,
                    status=FixStatus.PROCESSING,
                    message="GitHub issue created, Drupal fix pending",
                    github_issue_url=fix.github_issue_url,
                    github_issue_number=fix.github_issue_number,
                ))
            return results

        # Build the list of fixes to apply
        fixes_to_apply = []
        for fix, issue_data in content_fixes:
            user_instructions = fix.user_instructions or ""
            if not user_instructions:
                if fix.original_value and fix.proposed_value:
                    user_instructions = f"Change '{fix.original_value}' to '{fix.proposed_value}'"
                elif self._is_broken_link_issue(issue_data):
                    user_instructions = f"Fix or remove the broken link: {fix.original_value or 'see issue description'}"
                elif self._is_spelling_or_grammar_issue(issue_data):
                    user_instructions = f"Fix the spelling/grammar error"

            fixes_to_apply.append({
                "fix": fix,
                "issue_data": issue_data,
                "title": issue_data.get("title", "Unknown issue"),
                "description": issue_data.get("description", ""),
                "category": issue_data.get("category", "unknown"),
                "original_value": fix.original_value,
                "proposed_value": fix.proposed_value,
                "user_instructions": user_instructions,
            })

        logger.info(f"Applying {len(fixes_to_apply)} batched fixes to {page_url}")

        try:
            # Use the batched content fix generator
            from .content_fix_generator import generate_batched_content_fixes_sync

            batch_result = generate_batched_content_fixes_sync(
                page_url=page_url,
                fixes=fixes_to_apply,
            )

            if batch_result.get("success"):
                revision_url = batch_result.get("revision_url")
                diff_url = batch_result.get("diff_url")
                fix_messages = batch_result.get("fix_messages", {})

                # Update all fixes with success
                for fix, issue_data in content_fixes:
                    fix_message = fix_messages.get(fix.id, "Fix applied in batch")

                    # Update GitHub issue
                    try:
                        with self._get_github_client(github_repo) as client:
                            if fix.github_issue_number:
                                diff_section = ""
                                if diff_url:
                                    diff_section = f"**View diff (compare changes):** {diff_url}\n\n"

                                client.add_issue_comment(
                                    fix.github_issue_number,
                                    "✅ **Drupal Draft Revision Created (Batched)**\n\n"
                                    f"{fix_message}\n\n"
                                    f"**Review pending revision at:** {revision_url}\n\n"
                                    f"{diff_section}"
                                    f"This fix was applied along with {len(content_fixes) - 1} other fix(es) to the same page.\n\n"
                                    "The fix has been applied as a draft revision in **`ava_suggestion`** state.\n"
                                    "A human must review and approve the change before it goes live.\n\n"
                                    f"*Processed on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
                                )
                    except Exception as e:
                        logger.warning(f"Failed to update GitHub issue: {e}")

                    self.store.update_fix_status(
                        fix.id,
                        status=FixStatus.DRAFT_CREATED,
                        drupal_revision_url=revision_url,
                    )

                    results.append(FixResult(
                        fix_id=fix.id,
                        success=True,
                        status=FixStatus.DRAFT_CREATED,
                        message=fix_message,
                        github_issue_url=fix.github_issue_url,
                        github_issue_number=fix.github_issue_number,
                        drupal_revision_url=revision_url,
                    ))
            else:
                # Batch failed - report error for all fixes
                error_msg = batch_result.get("error", "Batched fix failed")
                for fix, issue_data in content_fixes:
                    self.store.update_fix_status(
                        fix.id,
                        status=FixStatus.PROCESSING,
                        error_message=error_msg,
                    )
                    results.append(FixResult(
                        fix_id=fix.id,
                        success=False,
                        status=FixStatus.PROCESSING,
                        message=f"Batched fix failed: {error_msg}",
                        github_issue_url=fix.github_issue_url,
                        github_issue_number=fix.github_issue_number,
                    ))

        except Exception as e:
            logger.error(f"Batched content fix error: {e}")
            for fix, issue_data in content_fixes:
                self.store.update_fix_status(
                    fix.id,
                    status=FixStatus.PROCESSING,
                    error_message=str(e),
                )
                results.append(FixResult(
                    fix_id=fix.id,
                    success=False,
                    status=FixStatus.PROCESSING,
                    message=f"Batched fix error: {e}",
                    github_issue_url=fix.github_issue_url,
                    github_issue_number=fix.github_issue_number,
                ))

        return results
