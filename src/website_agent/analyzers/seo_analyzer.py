from typing import List
from bs4 import BeautifulSoup

from website_agent.analyzers.base import Analyzer
from website_agent.models import Issue, PageResult, Severity


class SEOAnalyzer(Analyzer):
    category = "SEO"

    def analyze(self, page: PageResult) -> List[Issue]:
        if not page.content:
            return []

        soup = BeautifulSoup(page.content, "html.parser")
        issues: List[Issue] = []

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        if not title:
            issues.append(
                Issue(
                    category=self.category,
                    severity=Severity.high,
                    message="Missing or empty <title> tag",
                    location=str(page.url),
                )
            )

        meta_description = soup.find("meta", attrs={"name": "description"})
        if not meta_description or not meta_description.get("content", "").strip():
            issues.append(
                Issue(
                    category=self.category,
                    severity=Severity.medium,
                    message="Missing meta description",
                    location=str(page.url),
                )
            )

        h1_tags = soup.find_all("h1")
        if not h1_tags:
            issues.append(
                Issue(
                    category=self.category,
                    severity=Severity.medium,
                    message="Missing H1 heading",
                    location=str(page.url),
                )
            )
        elif len(h1_tags) > 1:
            issues.append(
                Issue(
                    category=self.category,
                    severity=Severity.low,
                    message="Multiple H1 headings detected",
                    location=page.url,
                    meta={"count": len(h1_tags)},
                )
            )

        return issues

