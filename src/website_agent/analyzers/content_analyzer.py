"""Content analyzer using LLM for spelling, grammar, and formatting issues.

Uses GPT-4o-mini to detect:
- Spelling errors (context-aware, ignores proper nouns)
- Grammar issues (subject-verb agreement, tense, etc.)
- Formatting problems (spacing, punctuation)
"""

import json
import logging
from typing import Optional

from bs4 import BeautifulSoup

from ..config import LLM_MODEL, OPENAI_API_KEY
from ..models import Issue, IssueCategory, Severity
from .base import BaseAnalyzer

logger = logging.getLogger(__name__)

# Only import openai if available
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class ContentAnalyzer(BaseAnalyzer):
    """LLM-powered analyzer for content quality issues."""

    category = IssueCategory.SPELLING  # Default, but creates issues for multiple categories

    def __init__(self, api_key: Optional[str] = None, model: str = LLM_MODEL):
        self.api_key = api_key or OPENAI_API_KEY
        self.model = model
        self.client = None

        if OPENAI_AVAILABLE and self.api_key:
            self.client = openai.OpenAI(api_key=self.api_key)

    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[Issue]:
        """Analyze page content for spelling, grammar, and formatting issues."""
        if not self.client:
            logger.warning("OpenAI client not available, skipping content analysis")
            return []

        if not text or len(text.strip()) < 50:
            logger.debug(f"Skipping content analysis for {url}: insufficient text")
            return []

        # Truncate very long text to avoid token limits
        max_chars = 8000
        truncated = text[:max_chars] if len(text) > max_chars else text

        try:
            result = self._analyze_with_llm(truncated, url)
            return self._parse_llm_response(result, url)
        except Exception as e:
            logger.error(f"LLM analysis failed for {url}: {e}")
            return []

    def _analyze_with_llm(self, text: str, url: str) -> dict:
        """Send text to LLM for analysis."""
        prompt = f"""Analyze the following website text for spelling errors, grammar mistakes, and formatting issues.

Text to analyze:
{text}

Return a JSON response with this structure:
{{
  "spelling_errors": [
    {{
      "word": "misspelled_word",
      "suggestion": "correct_spelling",
      "context": "The full sentence or paragraph containing the error (30-50 words)"
    }}
  ],
  "grammar_errors": [
    {{
      "issue": "Brief description of the grammar issue",
      "original": "The original problematic sentence or phrase",
      "suggestion": "The corrected version of the sentence/phrase",
      "context": "The full paragraph containing the issue for context (30-50 words)"
    }}
  ],
  "formatting_issues": [
    {{
      "issue": "description (e.g., double space, missing space after period)",
      "original": "The text as it appears",
      "suggestion": "The corrected version",
      "context": "The surrounding sentence (20-30 words)"
    }}
  ]
}}

RULES:

1. For SPELLING:
   - Flag words that are clearly misspelled (typos, wrong letters, missing letters)
   - The "word" field must contain the ACTUAL misspelled word from the text
   - SKIP these (not errors): proper nouns, company names, people names, place names
   - SKIP these (not errors): technical terms, industry jargon, brand names, acronyms
   - SKIP these (not errors): words that are correct but uncommon
   - Examples of real errors to flag: "teh" (the), "recieve" (receive), "occured" (occurred), "seperate" (separate)

2. For GRAMMAR:
   - "original" must be the EXACT text as it appears
   - "suggestion" must show the corrected sentence/phrase
   - For verb tense issues, show BOTH conflicting sentences
   - For serial comma issues, show the list and correction
   - Include enough context to locate and fix the issue

3. For FORMATTING:
   - Flag double spaces, missing spaces after punctuation, inconsistent spacing
   - "original" shows the problematic text exactly as it appears
   - "suggestion" shows the corrected version

Return ONLY valid JSON, no other text. If no issues found, return empty arrays.
Be thorough but accurate - flag clear errors, skip ambiguous cases."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional proofreader. Analyze text for spelling, grammar, and formatting errors. Return only valid JSON."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content.strip()
        return json.loads(content)

    def _parse_llm_response(self, result: dict, url: str) -> list[Issue]:
        """Convert LLM response to Issue objects."""
        issues = []

        # Process spelling errors
        for error in result.get("spelling_errors", []):
            word = error.get('word', 'unknown')
            suggestion = error.get('suggestion', 'check spelling')
            context = error.get('context', '')

            # Build element showing the context with the error highlighted
            element_text = f'"{word}" → "{suggestion}"'
            if context:
                element_text += f'\n\nContext:\n"{context}"'

            issues.append(Issue(
                category=IssueCategory.SPELLING,
                severity=Severity.MEDIUM,
                title=f"Spelling error: '{word}'",
                description=f"The word '{word}' appears to be misspelled.",
                recommendation=f"Change to: {suggestion}",
                url=url,
                element=element_text,
            ))

        # Process grammar errors
        for error in result.get("grammar_errors", []):
            issue_desc = error.get('issue', 'Grammar issue detected')
            original = error.get('original', '')
            suggestion = error.get('suggestion', 'Review and correct the grammar')
            context = error.get('context', '')

            # Build element showing original vs suggestion
            element_parts = []
            if original:
                element_parts.append(f'Original: "{original}"')
            if suggestion and suggestion != issue_desc:
                element_parts.append(f'Suggested: "{suggestion}"')
            if context and context != original:
                element_parts.append(f'\nContext:\n"{context}"')

            element_text = '\n'.join(element_parts) if element_parts else issue_desc

            issues.append(Issue(
                category=IssueCategory.GRAMMAR,
                severity=Severity.MEDIUM,
                title=f"Grammar issue: {issue_desc[:50]}",
                description=issue_desc,
                recommendation=suggestion if suggestion != issue_desc else "Review and correct the grammar",
                url=url,
                element=element_text,
            ))

        # Process formatting issues
        for error in result.get("formatting_issues", []):
            issue_desc = error.get('issue', 'Formatting issue detected')
            original = error.get('original', '')
            suggestion = error.get('suggestion', 'Fix the formatting')
            context = error.get('context', '')

            # Build element showing original vs suggestion
            element_parts = []
            if original:
                element_parts.append(f'Original: "{original}"')
            if suggestion and suggestion != issue_desc:
                element_parts.append(f'Suggested: "{suggestion}"')
            if context and context != original:
                element_parts.append(f'\nContext:\n"{context}"')

            element_text = '\n'.join(element_parts) if element_parts else issue_desc

            issues.append(Issue(
                category=IssueCategory.FORMATTING,
                severity=Severity.LOW,
                title=f"Formatting issue: {issue_desc[:50]}",
                description=issue_desc,
                recommendation=suggestion if suggestion != issue_desc else "Fix the formatting",
                url=url,
                element=element_text,
            ))

        return issues


class SpellingAnalyzer(ContentAnalyzer):
    """Convenience class that only returns spelling issues."""

    category = IssueCategory.SPELLING

    def analyze(self, url: str, html: str, text: str, soup: Optional[BeautifulSoup] = None) -> list[Issue]:
        all_issues = super().analyze(url, html, text, soup)
        return [i for i in all_issues if i.category == IssueCategory.SPELLING]


class GrammarAnalyzer(ContentAnalyzer):
    """Convenience class that only returns grammar issues."""

    category = IssueCategory.GRAMMAR

    def analyze(self, url: str, html: str, text: str, soup: Optional[BeautifulSoup] = None) -> list[Issue]:
        all_issues = super().analyze(url, html, text, soup)
        return [i for i in all_issues if i.category == IssueCategory.GRAMMAR]


class FormattingAnalyzer(ContentAnalyzer):
    """Convenience class that only returns formatting issues."""

    category = IssueCategory.FORMATTING

    def analyze(self, url: str, html: str, text: str, soup: Optional[BeautifulSoup] = None) -> list[Issue]:
        all_issues = super().analyze(url, html, text, soup)
        return [i for i in all_issues if i.category == IssueCategory.FORMATTING]
