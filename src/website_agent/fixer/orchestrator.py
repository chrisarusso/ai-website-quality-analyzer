"""Fix orchestrator for processing website quality fixes.

Coordinates the fix process:
1. Creates GitHub issues for tracking
2. Processes CODE_FIX issues via GitHub PRs
3. Processes CONTENT_FIX issues via Drupal API/Playwright
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..models import FixStatus, FixType, ProposedFix
from ..storage import SQLiteStore
from .classifier import FixClassifier
from .github_client import GitHubClient, GitHubClientError, GitHubIssue


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
        """
        self.store = store or SQLiteStore()
        self.classifier = FixClassifier()
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self.github_repo = github_repo

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
        """Process a CODE_FIX by creating a GitHub PR.

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

        try:
            with self._get_github_client(github_repo) as client:
                # Create a branch for the fix
                branch_name = f"fix/website-quality-{fix.id}"
                title = issue_data.get("title", "Unknown issue")

                try:
                    client.create_branch(branch_name)
                except GitHubClientError as e:
                    if "Reference already exists" not in str(e):
                        raise

                # Determine what file to modify based on issue type
                # This is a simplified version - real implementation would be more sophisticated
                fix_applied = False
                file_path = None
                new_content = None
                commit_message = None

                title_lower = title.lower()

                if "lang" in title_lower or "language declaration" in title_lower:
                    # Fix missing lang attribute
                    file_path = "web/themes/custom/flavor/templates/layout/html.html.twig"
                    try:
                        content, sha = client.get_file_content(file_path, client.get_default_branch())
                        if '<html' in content and 'lang=' not in content:
                            new_content = content.replace('<html', '<html lang="en"', 1)
                            commit_message = "Add lang attribute to html element for accessibility"
                            fix_applied = True
                    except GitHubClientError:
                        # File doesn't exist or can't be read
                        pass

                if fix_applied and file_path and new_content:
                    # Update the file
                    client.update_file(
                        path=file_path,
                        content=new_content,
                        message=commit_message,
                        branch=branch_name,
                        sha=sha,
                    )

                    # Create the PR
                    pr_body_parts = [
                        "## Website Quality Fix",
                        "",
                        f"Fixes #{fix.github_issue_number}",
                        "",
                        f"**Issue:** {title}",
                        f"**File:** `{file_path}`",
                        "",
                        "### Changes",
                        commit_message,
                    ]

                    if fix.user_instructions:
                        pr_body_parts.extend([
                            "",
                            "### User Notes",
                            fix.user_instructions,
                        ])

                    pr_body_parts.extend([
                        "",
                        "---",
                        "*Generated by Website Quality Agent*",
                    ])

                    pr = client.create_pull_request(
                        title=f"[Fix] {title}",
                        body="\n".join(pr_body_parts),
                        head=branch_name,
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
                        message=f"PR #{pr.number} created",
                        github_issue_url=fix.github_issue_url,
                        github_issue_number=fix.github_issue_number,
                        github_pr_url=pr.html_url,
                    )
                else:
                    # Can't auto-fix, update issue with comment
                    if fix.github_issue_number:
                        client.add_issue_comment(
                            fix.github_issue_number,
                            "⚠️ **Auto-fix not available**\n\n"
                            "This issue requires manual intervention. "
                            "The automated fixer could not determine how to apply the fix.\n\n"
                            f"*Processed on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
                        )

                    self.store.update_fix_status(
                        fix.id,
                        status=FixStatus.PROCESSING,
                        error_message="Auto-fix not available for this issue type",
                    )

                    return FixResult(
                        fix_id=fix.id,
                        success=True,  # Issue created successfully
                        status=FixStatus.PROCESSING,
                        message="GitHub issue created, manual fix required",
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

    def process_content_fix(
        self,
        fix: ProposedFix,
        issue_data: dict,
        github_repo: Optional[str] = None,
    ) -> FixResult:
        """Process a CONTENT_FIX by creating a Drupal draft revision.

        Args:
            fix: The proposed fix record
            issue_data: Data about the original issue
            github_repo: Repository for GitHub issue tracking

        Returns:
            FixResult with the outcome
        """
        # First create a GitHub issue for tracking
        if not fix.github_issue_url:
            issue_result = self.create_github_issue_for_fix(fix, issue_data, github_repo)
            if not issue_result.success:
                return issue_result

            fix.github_issue_url = issue_result.github_issue_url
            fix.github_issue_number = issue_result.github_issue_number

        # TODO: Implement Drupal integration via Playwright or JSON:API
        # For now, just mark as processing and add a comment to the GitHub issue

        try:
            with self._get_github_client(github_repo) as client:
                if fix.github_issue_number:
                    client.add_issue_comment(
                        fix.github_issue_number,
                        "📝 **Content Fix Required**\n\n"
                        "This is a content-level fix that needs to be made in the Drupal CMS.\n\n"
                        "**Steps:**\n"
                        "1. Log into the Drupal admin\n"
                        "2. Navigate to the content/media item\n"
                        "3. Make the required change\n"
                        "4. Save as draft for review\n\n"
                        f"*Processed on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
                    )

            self.store.update_fix_status(
                fix.id,
                status=FixStatus.PROCESSING,
                error_message="Drupal integration pending - manual fix required",
            )

            return FixResult(
                fix_id=fix.id,
                success=True,
                status=FixStatus.PROCESSING,
                message="GitHub issue created, Drupal fix pending",
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

        Args:
            batch_id: The batch ID to process
            issue_data_map: Map of fix_id -> issue data
            github_repo: Repository for GitHub operations

        Returns:
            List of FixResult for each fix
        """
        fixes = self.store.get_fixes_by_batch(batch_id)
        results = []

        for fix in fixes:
            issue_data = issue_data_map.get(fix.id, {})
            result = self.process_fix(fix, issue_data, github_repo)
            results.append(result)

        return results
