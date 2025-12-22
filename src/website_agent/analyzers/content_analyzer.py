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
      "context": "surrounding text (15-20 words)"
    }}
  ],
  "grammar_errors": [
    {{
      "issue": "description of grammar issue",
      "suggestion": "corrected version",
      "context": "surrounding text (15-20 words)"
    }}
  ],
  "formatting_issues": [
    {{
      "issue": "description (e.g., double space, missing space after period)",
      "suggestion": "corrected version",
      "context": "surrounding text (15-20 words)"
    }}
  ]
}}

IMPORTANT:
1. For SPELLING: Only flag actual misspellings. DO NOT flag:
   - Proper nouns (company names, people, places)
   - Technical terms (programming, industry jargon)
   - Brand names or product names
   - Intentional stylizations

2. For GRAMMAR: Flag issues like:
   - Subject-verb agreement
   - Incorrect verb tenses
   - Missing or incorrect articles
   - Run-on sentences
   - Comma splices
   - Its vs it's, their vs they're

3. For FORMATTING: Flag issues like:
   - Double spaces between words
   - Missing space after punctuation
   - Inconsistent spacing
   - Multiple punctuation marks

Return ONLY valid JSON, no other text. If no issues found, return empty arrays."""

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
            issues.append(Issue(
                category=IssueCategory.SPELLING,
                severity=Severity.MEDIUM,
                title=f"Spelling error: '{error.get('word', 'unknown')}'",
                description=f"The word '{error.get('word')}' appears to be misspelled.",
                recommendation=f"Consider changing to: {error.get('suggestion', 'check spelling')}",
                url=url,
                context=error.get("context"),
            ))

        # Process grammar errors
        for error in result.get("grammar_errors", []):
            issues.append(Issue(
                category=IssueCategory.GRAMMAR,
                severity=Severity.MEDIUM,
                title=f"Grammar issue: {error.get('issue', 'unknown')[:50]}",
                description=error.get("issue", "Grammar issue detected"),
                recommendation=error.get("suggestion", "Review and correct the grammar"),
                url=url,
                context=error.get("context"),
            ))

        # Process formatting issues
        for error in result.get("formatting_issues", []):
            issues.append(Issue(
                category=IssueCategory.FORMATTING,
                severity=Severity.LOW,
                title=f"Formatting issue: {error.get('issue', 'unknown')[:50]}",
                description=error.get("issue", "Formatting issue detected"),
                recommendation=error.get("suggestion", "Fix the formatting"),
                url=url,
                context=error.get("context"),
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
