"""GitHub client for creating issues and pull requests.

Handles:
- Creating GitHub issues for tracking fixes
- Creating branches for code fixes
- Updating files and creating commits
- Creating pull requests with fix details
- Local repo cloning and grep-based code search (avoids API rate limits)
"""

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


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


@dataclass
class CodeSearchResult:
    """Represents a code search result."""
    path: str
    html_url: str
    repository: str
    score: float
    text_matches: list[dict]  # Contains matched fragments with context


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

        # Local repo cache directory
        self._repo_cache_dir = Path(
            os.environ.get("REPO_CACHE_DIR", "/tmp/github-repo-cache")
        )
        self._local_repo_path: Optional[Path] = None
        self._current_branch: Optional[str] = None

    def _get_local_repo(self, branch: Optional[str] = None, pantheon_git_url: Optional[str] = None) -> Path:
        """Get or create a local clone of the repository.

        Args:
            branch: Specific branch to checkout (e.g., "demo-agent" for multidev)
            pantheon_git_url: If provided, clone from Pantheon instead of GitHub
                             (for multidev branches not in GitHub)

        Returns:
            Path to the local repository clone
        """
        logger.info(f"_get_local_repo called: branch={branch}, pantheon_git_url={'set' if pantheon_git_url else 'not set'}")

        # Create cache directory if needed
        self._repo_cache_dir.mkdir(parents=True, exist_ok=True)

        # Use repo name + branch as directory name to avoid conflicts
        dir_suffix = f"-{branch}" if branch else ""
        repo_dir = self._repo_cache_dir / f"{self.repo.replace('/', '-')}{dir_suffix}"
        logger.info(f"Repo cache directory: {repo_dir}")

        # Check if we need to switch branches
        if self._local_repo_path and self._local_repo_path.exists():
            if branch and self._current_branch != branch:
                # Need to checkout different branch
                self._checkout_branch(branch)
            else:
                self._git_pull()
            return self._local_repo_path

        if repo_dir.exists():
            # Repo already cloned
            logger.info(f"Using existing clone at {repo_dir}")
            self._local_repo_path = repo_dir
            if branch:
                self._checkout_branch(branch)
            else:
                self._git_pull()
        else:
            # Clone the repo
            if pantheon_git_url:
                # Clone from Pantheon (for multidev branches)
                clone_url = pantheon_git_url
                logger.info(f"Cloning from Pantheon to {repo_dir} (branch: {branch or 'default'})...")
                clone_args = ["git", "clone"]
                if branch:
                    clone_args.extend(["-b", branch])
                clone_args.extend(["--depth", "1", clone_url, str(repo_dir)])
            else:
                # Clone from GitHub with authentication
                clone_url = f"https://x-access-token:{self.token}@github.com/{self.repo}.git"
                logger.info(f"Cloning from GitHub {self.repo} to {repo_dir} (branch: {branch or 'default'})...")
                clone_args = ["git", "clone"]
                if branch:
                    clone_args.extend(["-b", branch])
                clone_args.extend(["--depth", "1", clone_url, str(repo_dir)])

            logger.info(f"Running clone command: git clone {'-b ' + branch if branch else ''} --depth 1 <url> {repo_dir}")
            result = subprocess.run(
                clone_args,
                capture_output=True,
                text=True,
                timeout=120,  # Add timeout
            )
            if result.returncode != 0:
                # Don't expose token in error message
                error_msg = result.stderr.replace(self.token, "***") if self.token else result.stderr
                logger.error(f"Clone failed: {error_msg}")
                raise GitHubClientError(f"Failed to clone repo: {error_msg}")
            logger.info(f"Clone successful to {repo_dir}")
            self._local_repo_path = repo_dir
            self._current_branch = branch

        return self._local_repo_path

    def _checkout_branch(self, branch: str) -> None:
        """Checkout a specific branch in the local repo."""
        if not self._local_repo_path:
            return

        # Fetch the branch if not available
        result = subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=self._local_repo_path,
            capture_output=True,
            text=True,
        )

        # Checkout the branch
        result = subprocess.run(
            ["git", "checkout", branch],
            cwd=self._local_repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Try creating from origin
            result = subprocess.run(
                ["git", "checkout", "-b", branch, f"origin/{branch}"],
                cwd=self._local_repo_path,
                capture_output=True,
                text=True,
            )

        if result.returncode == 0:
            self._current_branch = branch
            self._git_pull()

    def _git_pull(self) -> None:
        """Pull latest changes in the local repo."""
        if not self._local_repo_path:
            return

        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=self._local_repo_path,
            capture_output=True,
            text=True,
        )
        # Ignore pull errors (might be on detached HEAD, etc.)

    def search_code_local(
        self,
        query: str,
        paths: Optional[list[str]] = None,
        extensions: Optional[list[str]] = None,
        max_results: int = 10,
        branch: Optional[str] = None,
        pantheon_git_url: Optional[str] = None,
    ) -> list[CodeSearchResult]:
        """Search for code in the repository using local grep.

        Much faster than API and no rate limits!

        Args:
            query: Search query (text to find)
            paths: Limit search to specific paths (e.g., ["web/themes", "web/modules"])
            extensions: Limit to file extensions (e.g., ["twig", "html"])
            max_results: Maximum number of results to return
            branch: Specific branch to search (e.g., "demo-agent" for multidev)
            pantheon_git_url: Clone from Pantheon instead of GitHub

        Returns:
            List of CodeSearchResult with matching files and context
        """
        repo_path = self._get_local_repo(branch=branch, pantheon_git_url=pantheon_git_url)

        # Build grep command
        grep_args = [
            "grep",
            "-r",  # Recursive
            "-l",  # List files only
            "-i",  # Case insensitive
            "--include=*",  # Will be overridden if extensions specified
        ]

        # Add extension filters
        if extensions:
            # Remove the generic include and add specific ones
            grep_args = grep_args[:-1]  # Remove --include=*
            for ext in extensions:
                grep_args.append(f"--include=*.{ext}")

        grep_args.append(query)

        # Add search paths or use repo root
        if paths:
            for path in paths:
                full_path = repo_path / path
                if full_path.exists():
                    grep_args.append(str(full_path))
        else:
            grep_args.append(str(repo_path))

        # Run grep
        result = subprocess.run(
            grep_args,
            capture_output=True,
            text=True,
            cwd=repo_path,
        )

        # Parse results
        results = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            # Convert absolute path to relative path
            try:
                file_path = Path(line)
                if file_path.is_absolute():
                    rel_path = file_path.relative_to(repo_path)
                else:
                    rel_path = Path(line)

                # Get context around the match
                context_result = subprocess.run(
                    ["grep", "-n", "-C", "2", query, str(file_path)],
                    capture_output=True,
                    text=True,
                )
                context = context_result.stdout[:500] if context_result.stdout else ""

                results.append(
                    CodeSearchResult(
                        path=str(rel_path),
                        html_url=f"https://github.com/{self.repo}/blob/main/{rel_path}",
                        repository=self.repo,
                        score=1.0,
                        text_matches=[{"fragment": context}] if context else [],
                    )
                )

                if len(results) >= max_results:
                    break

            except (ValueError, OSError):
                continue

        return results

    def get_file_content_local(
        self,
        path: str,
        branch: Optional[str] = None,
        pantheon_git_url: Optional[str] = None,
    ) -> tuple[str, str]:
        """Get file content from local clone.

        Args:
            path: Path to file in repo
            branch: Specific branch to read from (e.g., "demo-agent" for multidev)
            pantheon_git_url: Clone from Pantheon instead of GitHub

        Returns:
            Tuple of (content, sha)
        """
        repo_path = self._get_local_repo(branch=branch, pantheon_git_url=pantheon_git_url)
        file_path = repo_path / path

        if not file_path.exists():
            raise GitHubClientError(f"File not found: {path}")

        content = file_path.read_text()

        # Get file SHA from git
        result = subprocess.run(
            ["git", "hash-object", str(file_path)],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )
        sha = result.stdout.strip() if result.returncode == 0 else ""

        # We need the blob SHA for the API, get it properly
        # Actually, for updating via API we need the current file's blob SHA
        # Let's fetch it from API to be safe
        try:
            _, api_sha = self.get_file_content(path, ref=branch)
            return content, api_sha
        except GitHubClientError:
            return content, sha

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

    def search_code(
        self,
        query: str,
        path: Optional[str] = None,
        extension: Optional[str] = None,
        max_results: int = 10,
    ) -> list[CodeSearchResult]:
        """Search for code in the repository.

        Args:
            query: Search query (text to find)
            path: Limit search to specific path (e.g., "web/themes")
            extension: Limit to file extension (e.g., "twig", "html")
            max_results: Maximum number of results to return

        Returns:
            List of CodeSearchResult with matching files and context
        """
        # Build the search query
        q_parts = [f'"{query}"', f"repo:{self.repo}"]

        if path:
            q_parts.append(f"path:{path}")
        if extension:
            q_parts.append(f"extension:{extension}")

        full_query = " ".join(q_parts)

        # Make request with text-match media type for context
        response = self._client.request(
            "GET",
            "/search/code",
            params={"q": full_query, "per_page": max_results},
            headers={
                **self._client.headers,
                "Accept": "application/vnd.github.text-match+json",
            },
        )

        if not response.is_success:
            # Search may return 422 for invalid queries - treat as empty result
            if response.status_code == 422:
                return []
            error_msg = response.json().get("message", response.text)
            raise GitHubClientError(
                f"GitHub API error ({response.status_code}): {error_msg}"
            )

        data = response.json()
        results = []

        for item in data.get("items", [])[:max_results]:
            results.append(
                CodeSearchResult(
                    path=item["path"],
                    html_url=item["html_url"],
                    repository=item["repository"]["full_name"],
                    score=item.get("score", 0.0),
                    text_matches=item.get("text_matches", []),
                )
            )

        return results

    def search_for_text_in_templates(
        self,
        text: str,
        template_paths: Optional[list[str]] = None,
        use_local: bool = True,
        branch: Optional[str] = None,
        pantheon_git_url: Optional[str] = None,
    ) -> list[CodeSearchResult]:
        """Search for specific text in template files.

        Searches common template locations for Drupal/Jekyll sites.
        Uses local clone + grep by default (faster, no rate limits).

        Args:
            text: The text to find (e.g., a misspelled word or phrase)
            template_paths: Optional list of paths to search
            use_local: If True, use local clone + grep (default). If False, use API.
            branch: Specific branch to search (e.g., "demo-agent" for multidev)
            pantheon_git_url: Clone from Pantheon instead of GitHub

        Returns:
            List of matching files with context
        """
        if template_paths is None:
            # Common template locations for Drupal/Jekyll
            # Order matters: custom themes first, then contrib
            template_paths = [
                "web/themes/custom",  # Custom themes first (most likely to need edits)
                "web/modules/custom",  # Custom modules
                "web/themes/contrib",  # Contrib themes (less likely)
                "web/modules/contrib",  # Contrib modules (less likely)
                "web/themes",  # Catch-all for themes
                "web/modules",  # Catch-all for modules
                "_layouts",
                "_includes",
                "templates",
            ]

        # Use local search by default (much faster, no rate limits)
        if use_local:
            results = self.search_code_local(
                query=text,
                paths=template_paths,
                extensions=["twig", "html", "php", "md", "yml", "yaml"],
                max_results=20,
                branch=branch,
                pantheon_git_url=pantheon_git_url,
            )
            # Sort results to prioritize custom themes over contrib
            def priority_key(r):
                path = r.path.lower()
                if '/custom/' in path:
                    return 0  # Highest priority
                elif '/contrib/' in path:
                    return 2  # Lower priority
                else:
                    return 1  # Middle priority
            results.sort(key=priority_key)
            return results

        # Fallback to API search if local is disabled
        all_results = []

        # Search each template path
        for path in template_paths:
            try:
                results = self.search_code(
                    query=text,
                    path=path,
                    max_results=5,
                )
                all_results.extend(results)
            except GitHubClientError:
                # Path may not exist, continue
                continue

        # Also search without path restriction for common template extensions
        for ext in ["twig", "html", "html.twig", "md"]:
            try:
                results = self.search_code(
                    query=text,
                    extension=ext,
                    max_results=5,
                )
                # Dedupe by path
                existing_paths = {r.path for r in all_results}
                for r in results:
                    if r.path not in existing_paths:
                        all_results.append(r)
                        existing_paths.add(r.path)
            except GitHubClientError:
                continue

        return all_results

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
        original_value: Optional[str] = None,
        proposed_value: Optional[str] = None,
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
            original_value: Original problematic value (optional)
            proposed_value: Suggested fix value (optional)

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

        # Show original and suggested values as separate blocks (not inline)
        if original_value or proposed_value:
            body_parts.extend([
                "",
                "### Original",
                "```",
                original_value or "(not specified)",
                "```",
                "",
                "### Suggested",
                "```",
                proposed_value or "(not specified)",
                "```",
            ])

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
