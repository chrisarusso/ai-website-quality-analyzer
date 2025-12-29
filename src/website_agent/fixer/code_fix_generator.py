"""LLM-powered code fix generator.

Simple approach:
1. Search for original_value directly in the codebase
2. For multi-word phrases, use HTML-aware regex (allows tags between words)
3. Fix ALL matching files, not just the first one
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .github_client import GitHubClient, CodeSearchResult

logger = logging.getLogger(__name__)

# Only import openai if available
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@dataclass
class CodeFix:
    """A generated code fix for a single file."""
    file_path: str
    original_content: str
    fixed_content: str
    file_sha: str  # For creating commit
    explanation: str
    confidence: float  # 0.0 to 1.0


@dataclass
class CodeFixResult:
    """Result of attempting to generate code fixes."""
    success: bool
    message: str
    fixes: list[CodeFix] = field(default_factory=list)  # Can have multiple fixes
    search_results: Optional[list[CodeSearchResult]] = None
    error: Optional[str] = None

    # Backwards compatibility - return first fix
    @property
    def fix(self) -> Optional[CodeFix]:
        return self.fixes[0] if self.fixes else None


class CodeFixGenerator:
    """Generates code fixes using LLM based on issues and user instructions."""

    def __init__(
        self,
        github_client: GitHubClient,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ):
        """Initialize the code fix generator.

        Args:
            github_client: GitHub client for searching and retrieving files
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: LLM model to use for fix generation
        """
        self.github = github_client
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.client = None

        if OPENAI_AVAILABLE and self.api_key:
            self.client = openai.OpenAI(api_key=self.api_key)

    def _build_html_aware_pattern(self, text: str, use_word_boundaries: bool = True) -> str:
        """Build a regex pattern that matches text with optional HTML tags between words.

        Example: "i liek food" matches "i liek <a href='...'>food</a>"

        Args:
            text: The text to search for
            use_word_boundaries: If True, add \\b word boundaries to prevent partial matches

        Returns:
            Regex pattern string
        """
        # Split into words
        words = text.split()

        if len(words) == 1:
            # Single word - escape it and optionally add word boundaries
            escaped = re.escape(words[0])
            if use_word_boundaries:
                return r'\b' + escaped + r'\b'
            return escaped

        # Multi-word: allow optional HTML tags and whitespace between words
        # Pattern allows: whitespace, then optional <...> tags, then whitespace
        html_gap = r'(?:\s*(?:<[^>]*>\s*)*)'

        pattern_parts = []
        if use_word_boundaries:
            pattern_parts.append(r'\b')
        pattern_parts.append(re.escape(words[0]))
        for word in words[1:]:
            pattern_parts.append(html_gap)
            pattern_parts.append(re.escape(word))
        if use_word_boundaries:
            pattern_parts.append(r'\b')

        return ''.join(pattern_parts)

    def generate_fix(
        self,
        issue_title: str,
        issue_description: str,
        page_url: str,
        user_instructions: str,
        original_value: Optional[str] = None,
        proposed_value: Optional[str] = None,
        category: str = "unknown",
        branch: Optional[str] = None,
        pantheon_git_url: Optional[str] = None,
    ) -> CodeFixResult:
        """Generate code fixes for an issue.

        Simple approach:
        1. Search for original_value directly
        2. Fix ALL matching files

        Args:
            issue_title: Title of the quality issue
            issue_description: Full description of the issue
            page_url: URL where the issue was found
            user_instructions: User-provided context and instructions
            original_value: Original text/value that's wrong (required for matching)
            proposed_value: Proposed fix value (optional)
            category: Issue category (spelling, accessibility, etc.)
            branch: Branch to search in (e.g., "demo-agent" for Pantheon multidev)
            pantheon_git_url: Clone from Pantheon instead of GitHub

        Returns:
            CodeFixResult with generated fixes for all matching files
        """
        if not self.client:
            return CodeFixResult(
                success=False,
                message="OpenAI client not available",
                error="No API key or openai package not installed",
            )

        if not original_value:
            return CodeFixResult(
                success=False,
                message="No original_value provided - cannot search for text to fix",
                error="original_value is required for code fixes",
            )

        logger.info(f"Code fix: searching for '{original_value}' (branch: {branch or 'default'})")

        # Step 1: Simple search - just look for the original_value
        search_results = self.github.search_for_text_in_templates(
            original_value,
            branch=branch,
            pantheon_git_url=pantheon_git_url,
        )

        if not search_results:
            # Try with just the first word if multi-word (might have HTML in between)
            words = original_value.split()
            if len(words) > 1:
                logger.info(f"No results for full phrase, trying first word: '{words[0]}'")
                search_results = self.github.search_for_text_in_templates(
                    words[0],
                    branch=branch,
                    pantheon_git_url=pantheon_git_url,
                )

        if not search_results:
            return CodeFixResult(
                success=False,
                message=f"Could not find '{original_value}' in codebase",
                search_results=[],
                error="No matching files found",
            )

        logger.info(f"Found {len(search_results)} potential files")

        # Step 2: For each file, check if it actually contains the text and generate a fix
        # Build HTML-aware pattern for multi-word searches
        html_pattern = self._build_html_aware_pattern(original_value)
        logger.info(f"Using pattern: {html_pattern}")

        fixes = []
        files_checked = 0
        files_matched = 0

        for result in search_results:
            files_checked += 1
            try:
                # IMPORTANT: If we searched in Pantheon, we still need to commit to GitHub
                # So we need to get the file content and SHA from the GitHub target branch
                if pantheon_git_url:
                    # Get file from GitHub's target branch (configured via GITHUB_TARGET_BRANCH)
                    target_branch = os.environ.get("GITHUB_TARGET_BRANCH")
                    try:
                        github_content, github_sha = self.github.get_file_content(result.path, ref=target_branch)
                        file_content = github_content
                        file_sha = github_sha
                        logger.info(f"Got {result.path} from GitHub {target_branch or 'default'} (SHA: {github_sha[:8]})")
                    except Exception as e:
                        logger.warning(f"Could not get {result.path} from GitHub, skipping: {e}")
                        continue
                else:
                    # Not using Pantheon - get from local clone
                    file_content, file_sha = self.github.get_file_content_local(
                        result.path,
                        branch=branch,
                        pantheon_git_url=pantheon_git_url,
                    )

                # Check if file actually contains the text (with HTML-aware matching)
                if not re.search(html_pattern, file_content, re.IGNORECASE):
                    logger.debug(f"File {result.path} doesn't match pattern in GitHub, skipping")
                    continue

                files_matched += 1
                logger.info(f"File {result.path} matches - generating fix")

                # Generate fix for this file
                fix_result = self._generate_fix_with_llm(
                    file_path=result.path,
                    file_content=file_content,
                    issue_title=issue_title,
                    issue_description=issue_description,
                    page_url=page_url,
                    user_instructions=user_instructions,
                    original_value=original_value,
                    proposed_value=proposed_value,
                    category=category,
                )

                if fix_result and fix_result["fixed_content"] != file_content:
                    fixes.append(CodeFix(
                        file_path=result.path,
                        original_content=file_content,
                        fixed_content=fix_result["fixed_content"],
                        file_sha=file_sha,
                        explanation=fix_result["explanation"],
                        confidence=fix_result["confidence"],
                    ))
                    logger.info(f"Fix generated for {result.path}")

            except Exception as e:
                logger.warning(f"Error processing {result.path}: {e}")
                continue

        if not fixes:
            return CodeFixResult(
                success=False,
                message=f"Found {files_matched} files with matches but could not generate fixes",
                search_results=search_results,
                error="LLM could not generate valid fixes",
            )

        return CodeFixResult(
            success=True,
            message=f"Generated {len(fixes)} fix(es) for '{original_value}'",
            fixes=fixes,
            search_results=search_results,
        )

    def _extract_context_window(
        self,
        file_content: str,
        search_text: str,
        window_lines: int = 20,
    ) -> tuple[str, int, int]:
        """Extract a window of lines around where search_text appears.

        Returns:
            Tuple of (context_with_line_numbers, start_line, end_line)
        """
        lines = file_content.split('\n')

        # Find the line containing the search text
        target_line = -1
        pattern = self._build_html_aware_pattern(search_text)
        for i, line in enumerate(lines):
            if re.search(pattern, line, re.IGNORECASE):
                target_line = i
                break

        if target_line == -1:
            # Fallback: simple substring search
            for i, line in enumerate(lines):
                if search_text.lower() in line.lower():
                    target_line = i
                    break

        if target_line == -1:
            # Still not found - return first chunk
            start = 0
            end = min(window_lines * 2, len(lines))
        else:
            # Window around the target line
            start = max(0, target_line - window_lines)
            end = min(len(lines), target_line + window_lines + 1)

        # Build context with line numbers
        context_lines = []
        for i in range(start, end):
            context_lines.append(f"{i + 1:4d}: {lines[i]}")

        return '\n'.join(context_lines), start, end

    def _generate_fix_with_llm(
        self,
        file_path: str,
        file_content: str,
        issue_title: str,
        issue_description: str,
        page_url: str,
        user_instructions: str,
        original_value: Optional[str],
        proposed_value: Optional[str],
        category: str,
    ) -> Optional[dict]:
        """Use LLM to generate the actual fix.

        Returns:
            Dict with fixed_content, explanation, and confidence, or None on failure
        """
        # For large files, extract a window around the match
        max_content_len = 12000
        lines = file_content.split('\n')

        if len(file_content) > max_content_len and original_value:
            # Extract context window around the match
            context, start_line, end_line = self._extract_context_window(
                file_content, original_value, window_lines=30
            )
            use_line_replacement = True
            logger.info(f"Large file ({len(file_content)} chars), using line replacement for lines {start_line+1}-{end_line}")
        else:
            # Small file - use whole content
            context = file_content
            start_line = 0
            end_line = len(lines)
            use_line_replacement = False

        if use_line_replacement:
            prompt = f"""You are a code fixer. Fix the specified text in this file excerpt.

## File: {file_path} (lines {start_line + 1}-{end_line})

```
{context}
```

## What to Fix
**Find:** {original_value}
**Replace with:** {proposed_value or 'Fix the issue appropriately'}

## Context
**Issue:** {issue_title}
**Category:** {category}

## CRITICAL RULES
1. Find "{original_value}" in the excerpt above
2. Replace ONLY that exact text with "{proposed_value}"
3. Return the EXACT file line(s) that need changing (each line as shown with its line number above)
4. PRESERVE the exact line breaks - do NOT combine multiple lines into one
5. PRESERVE all leading whitespace, indentation, HTML tags, and other content on that line
6. ONLY change the specific text mentioned - nothing else

IMPORTANT:
- A "line" is ONE row from the file (as shown with line numbers above)
- Do NOT merge content from multiple lines - each line entry should be ONE file line
- If the text to fix is on line 259, return line 259 exactly as it should be (not content from lines 260-261)

Return JSON:
{{
    "fixed_lines": {{
        "259": "          <p>From launch to ongoing support, we ensure your application runs smoothly,"
    }},
    "explanation": "Changed run to runs on line 259",
    "confidence": 0.9
}}

Return ONLY valid JSON with the line numbers and their exact single-line content."""
        else:
            prompt = f"""You are a code fixer. Fix the specified text in this file.

## File: {file_path}

```
{context}
```

## What to Fix
**Find:** {original_value}
**Replace with:** {proposed_value or 'Fix the issue appropriately'}

## Context
**Issue:** {issue_title}
**Category:** {category}
**Description:** {issue_description}
**User Instructions:** {user_instructions or 'None'}

## Rules
1. Find "{original_value}" in the file (it may have HTML tags mixed in)
2. Replace it with the corrected version
3. Return the COMPLETE file with the fix applied
4. Do NOT change anything else

Return JSON:
{{
    "fixed_content": "Complete file content with fix applied",
    "explanation": "Changed X to Y",
    "confidence": 0.9
}}

Return ONLY valid JSON."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise code fixer. Make only the specified change. Return valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=16000,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content.strip()
            result = json.loads(content)

            # Handle line replacement response (for large files)
            if "fixed_lines" in result:
                fixed_lines = result["fixed_lines"]
                if not fixed_lines:
                    logger.error("LLM returned empty fixed_lines")
                    return None

                # Reconstruct the full file with replaced lines
                file_lines = file_content.split('\n')
                for line_num_str, new_content in fixed_lines.items():
                    try:
                        line_idx = int(line_num_str) - 1  # Convert to 0-indexed
                        if 0 <= line_idx < len(file_lines):
                            file_lines[line_idx] = new_content
                            logger.info(f"Replaced line {line_num_str}")
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Invalid line number {line_num_str}: {e}")

                fixed_content = '\n'.join(file_lines)
                return {
                    "fixed_content": fixed_content,
                    "explanation": result.get("explanation", "Fix applied"),
                    "confidence": float(result.get("confidence", 0.5)),
                }

            # Handle full file response (for small files)
            if "fixed_content" not in result:
                logger.error("LLM response missing both fixed_content and fixed_lines")
                return None

            return {
                "fixed_content": result["fixed_content"],
                "explanation": result.get("explanation", "Fix applied"),
                "confidence": float(result.get("confidence", 0.5)),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM fix generation failed: {e}")
            return None

    def create_fix_pr(
        self,
        fixes: list[CodeFix],
        issue_title: str,
        issue_url: Optional[str] = None,
        target_branch: Optional[str] = None,
    ) -> Optional[dict]:
        """Create a pull request with multiple file fixes.

        Args:
            fixes: List of CodeFix objects to apply
            issue_title: Title for the PR
            issue_url: Optional URL to the GitHub issue to reference
            target_branch: Branch to merge into

        Returns:
            Dict with PR details or None on failure
        """
        from datetime import datetime

        if not fixes:
            logger.error("No fixes to create PR for")
            return None

        # Generate a unique branch name
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"fix/{timestamp}-auto-fix"

        try:
            # Create branch from target branch
            self.github.create_branch(branch_name, from_branch=target_branch)

            # Update each file
            for fix in fixes:
                self.github.update_file(
                    path=fix.file_path,
                    content=fix.fixed_content,
                    message=f"fix: {issue_title} in {fix.file_path}\n\n{fix.explanation}",
                    branch=branch_name,
                    sha=fix.file_sha,
                )
                logger.info(f"Updated {fix.file_path} in branch {branch_name}")

            # Build PR body
            pr_body_parts = [
                "## Automated Fix",
                "",
                f"**Issue:** {issue_title}",
                "",
                "### Files Changed",
            ]

            for fix in fixes:
                pr_body_parts.append(f"- `{fix.file_path}` - {fix.explanation} (confidence: {fix.confidence:.0%})")

            if issue_url:
                pr_body_parts.extend(["", f"Fixes: {issue_url}"])

            pr_body_parts.extend([
                "",
                "---",
                "*Generated by Website Quality Agent*",
            ])

            pr = self.github.create_pull_request(
                title=f"fix: {issue_title}",
                body="\n".join(pr_body_parts),
                head=branch_name,
                base=target_branch,
            )

            return {
                "pr_number": pr.number,
                "pr_url": pr.html_url,
                "branch": branch_name,
                "files_changed": len(fixes),
            }

        except Exception as e:
            logger.error(f"Failed to create PR: {e}")
            return None
