import re
from typing import List

from website_agent.analyzers.base import Analyzer
from website_agent.models import Issue, PageResult, Severity


class ContentAnalyzer(Analyzer):
    category = "Content"

    def analyze(self, page: PageResult) -> List[Issue]:
        if not page.content:
            return []

        text = self._extract_text(page.content)
        issues: List[Issue] = []

        double_space_snippets = self._find_double_space_snippets(text)
        if double_space_snippets:
            issues.append(
                Issue(
                    category=self.category,
                    severity=Severity.low,
                    message="Detected double spaces in copy",
                    location=str(page.url),
                    meta={"snippets": double_space_snippets},
                )
            )

        word_count = len(text.split())
        if word_count < 50:
            issues.append(
                Issue(
                    category=self.category,
                    severity=Severity.medium,
                    message="Thin content detected (under 50 words)",
                    location=str(page.url),
                    meta={"word_count": word_count, "preview": text[:160]},
                )
            )

        return issues

    def _extract_text(self, html: str) -> str:
        # quick & light text extractor to avoid heavier parsing
        cleaned = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\\s+", " ", cleaned)
        return cleaned.strip()

    def _find_double_space_snippets(self, text: str, max_snippets: int = 3, context: int = 40) -> List[str]:
        snippets: List[str] = []
        search_from = 0
        while len(snippets) < max_snippets:
            idx = text.find("  ", search_from)
            if idx == -1:
                break
            start = max(idx - context, 0)
            end = min(idx + 2 + context, len(text))
            snippet = text[start:end].strip()
            snippets.append(snippet)
            search_from = idx + 2
        return snippets

