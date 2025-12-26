"""GitHub client for creating issues and pull requests.

Handles:
- Creating GitHub issues for tracking fixes
- Creating branches for code fixes
- Updating files and creating commits
- Creating pull requests with fix details
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx


@dataclass
class GitHubIssue:
    """Represents a GitHub issue."""
    number: int
    url: str
    html_url: str
    title: str
    state: str


@dataclass
class GitHubPR:
    """Represents a GitHub pull request."""
    number: int
    url: str
    html_url: str
    title: str
    state: str
    head_ref: str


class GitHubClientError(Exception):
    """Error from GitHub API."""
    pass


class GitHubClient:
    """Client for GitHub API operations."""

    BASE_URL = "https://api.github.com"

    def __init__(
        self,
        token: Optional[str] = None,
        repo: str = "savaslabs/savaslabs.com",
    ):
        """Initialize GitHub client.

        Args:
            token: GitHub personal access token. If not provided, reads from GITHUB_TOKEN env var.
            repo: Repository in "owner/repo" format.
        """
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise GitHubClientError(
                "GitHub token not provided. Set GITHUB_TOKEN environment variable."
            )

        self.repo = repo
        self.owner, self.repo_name = repo.split("/")

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an API request."""
        response = self._client.request(method, path, **kwargs)

        if not response.is_success:
            error_msg = response.json().get("message", response.text)
            raise GitHubClientError(
                f"GitHub API error ({response.status_code}): {error_msg}"
            )

        if response.status_code == 204:  # No content
            return {}

        return response.json()

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> GitHubIssue:
        """Create a new GitHub issue.

        Args:
            title: Issue title
            body: Issue body (markdown)
            labels: List of label names to apply

        Returns:
            GitHubIssue with created issue details
        """
        data = {
            "title": title,
            "body": body,
        }
        if labels:
            data["labels"] = labels

        result = self._request(
            "POST",
            f"/repos/{self.repo}/issues",
            json=data,
        )

        return GitHubIssue(
            number=result["number"],
            url=result["url"],
            html_url=result["html_url"],
            title=result["title"],
            state=result["state"],
        )

    def add_issue_comment(self, issue_number: int, body: str) -> dict:
        """Add a comment to an issue.

        Args:
            issue_number: The issue number
            body: Comment body (markdown)

        Returns:
            Comment data from API
        """
        return self._request(
            "POST",
            f"/repos/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

    def close_issue(self, issue_number: int) -> dict:
        """Close an issue.

        Args:
            issue_number: The issue number to close

        Returns:
            Updated issue data
        """
        return self._request(
            "PATCH",
            f"/repos/{self.repo}/issues/{issue_number}",
            json={"state": "closed"},
        )

    def get_default_branch(self) -> str:
        """Get the default branch of the repository.

        Returns:
            Name of the default branch (e.g., "main" or "master")
        """
        result = self._request("GET", f"/repos/{self.repo}")
        return result["default_branch"]

    def get_branch_sha(self, branch: str) -> str:
        """Get the SHA of the latest commit on a branch.

        Args:
            branch: Branch name

        Returns:
            SHA of the branch head
        """
        result = self._request(
            "GET",
            f"/repos/{self.repo}/git/ref/heads/{branch}",
        )
        return result["object"]["sha"]

    def create_branch(self, branch_name: str, from_branch: Optional[str] = None) -> str:
        """Create a new branch.

        Args:
            branch_name: Name for the new branch
            from_branch: Branch to create from (defaults to default branch)

        Returns:
            SHA of the new branch
        """
        if from_branch is None:
            from_branch = self.get_default_branch()

        base_sha = self.get_branch_sha(from_branch)

        result = self._request(
            "POST",
            f"/repos/{self.repo}/git/refs",
            json={
                "ref": f"refs/heads/{branch_name}",
                "sha": base_sha,
            },
        )

        return result["object"]["sha"]

    def get_file_content(self, path: str, ref: Optional[str] = None) -> tuple[str, str]:
        """Get the content and SHA of a file.

        Args:
            path: Path to file in repo
            ref: Branch, tag, or commit (optional)

        Returns:
            Tuple of (content, sha)
        """
        import base64

        params = {}
        if ref:
            params["ref"] = ref

        result = self._request(
            "GET",
            f"/repos/{self.repo}/contents/{path}",
            params=params,
        )

        content = base64.b64decode(result["content"]).decode("utf-8")
        return content, result["sha"]

    def update_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str,
        sha: Optional[str] = None,
    ) -> dict:
        """Update or create a file in the repository.

        Args:
            path: Path to file in repo
            content: New file content
            message: Commit message
            branch: Branch to commit to
            sha: Current file SHA (required for updates, not for creates)

        Returns:
            Commit data from API
        """
        import base64

        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        data = {
            "message": message,
            "content": encoded_content,
            "branch": branch,
        }

        if sha:
            data["sha"] = sha

        return self._request(
            "PUT",
            f"/repos/{self.repo}/contents/{path}",
            json=data,
        )

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: Optional[str] = None,
    ) -> GitHubPR:
        """Create a pull request.

        Args:
            title: PR title
            body: PR body (markdown)
            head: The branch containing the changes
            base: The branch to merge into (defaults to default branch)

        Returns:
            GitHubPR with created PR details
        """
        if base is None:
            base = self.get_default_branch()

        result = self._request(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )

        return GitHubPR(
            number=result["number"],
            url=result["url"],
            html_url=result["html_url"],
            title=result["title"],
            state=result["state"],
            head_ref=head,
        )

    def create_issue_from_quality_issue(
        self,
        category: str,
        severity: str,
        title: str,
        description: str,
        recommendation: str,
        url: str,
        element: Optional[str] = None,
        user_instructions: Optional[str] = None,
        fix_type: Optional[str] = None,
    ) -> GitHubIssue:
        """Create a GitHub issue from a website quality issue.

        Args:
            category: Issue category (seo, accessibility, etc.)
            severity: Issue severity (critical, high, medium, low)
            title: Issue title
            description: Issue description
            recommendation: How to fix the issue
            url: URL where issue was found
            element: HTML element or context (optional)
            user_instructions: User-provided fix instructions (optional)
            fix_type: Fix type classification (optional)

        Returns:
            GitHubIssue with created issue details
        """
        # Build the issue body
        body_parts = [
            "## Website Quality Issue",
            "",
            f"**Category:** {category.upper()} | **Severity:** {severity.upper()} | **URL:** {url}",
            "",
            "### Description",
            description or title,
            "",
            "### Recommendation",
            recommendation,
        ]

        if element:
            body_parts.extend([
                "",
                "### HTML Context",
                "```html",
                element,
                "```",
            ])

        if user_instructions:
            body_parts.extend([
                "",
                "### User Instructions",
                user_instructions,
            ])

        if fix_type:
            body_parts.extend([
                "",
                f"**Fix Type:** `{fix_type}`",
            ])

        body_parts.extend([
            "",
            "---",
            f"*Generated by Website Quality Agent on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*",
        ])

        body = "\n".join(body_parts)

        # Build labels
        labels = ["website-quality", category.lower()]
        if severity.lower() in ("critical", "high"):
            labels.append(f"priority:{severity.lower()}")
        if fix_type:
            labels.append(f"fix-type:{fix_type.lower().replace('_', '-')}")

        # Create the issue
        issue_title = f"[{category.upper()}] {title}"

        return self.create_issue(
            title=issue_title,
            body=body,
            labels=labels,
        )

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
