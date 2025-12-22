"""SEO analyzer for detecting search engine optimization issues.

Checks for:
- Missing/duplicate title tags
- Missing/duplicate meta descriptions
- Missing or multiple H1 tags
- Canonical URL issues
- Structured data presence
- Open Graph tags
- Sitemap and robots.txt (site-level)
"""

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from ..models import Issue, IssueCategory, Severity
from .base import BaseAnalyzer


class SEOAnalyzer(BaseAnalyzer):
    """Analyzer for SEO-related issues."""

    category = IssueCategory.SEO

    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[Issue]:
        """Analyze page for SEO issues."""
        issues = []
        soup = self._get_soup(html, soup)

        # Check title tag
        issues.extend(self._check_title(soup, url))

        # Check meta description
        issues.extend(self._check_meta_description(soup, url))

        # Check H1 tags
        issues.extend(self._check_h1(soup, url))

        # Check canonical URL
        issues.extend(self._check_canonical(soup, url))

        # Check structured data
        issues.extend(self._check_structured_data(soup, url))

        # Check Open Graph tags
        issues.extend(self._check_open_graph(soup, url))

        # Check heading hierarchy
        issues.extend(self._check_heading_hierarchy(soup, url))

        return issues

    def _check_title(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for title tag issues."""
        issues = []
        title = soup.find("title")

        if not title:
            issues.append(self._create_issue(
                severity=Severity.HIGH,
                title="Missing title tag",
                description="The page does not have a title tag, which is critical for SEO and user experience.",
                recommendation="Add a unique, descriptive title tag between 50-60 characters.",
                url=url,
                element="<title>",
            ))
        elif not title.string or not title.string.strip():
            issues.append(self._create_issue(
                severity=Severity.HIGH,
                title="Empty title tag",
                description="The title tag exists but is empty.",
                recommendation="Add descriptive text to the title tag.",
                url=url,
                element="<title>",
            ))
        else:
            title_text = title.string.strip()
            if len(title_text) < 30:
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title="Title tag too short",
                    description=f"Title is only {len(title_text)} characters. Short titles may not be descriptive enough.",
                    recommendation="Expand the title to 50-60 characters with relevant keywords.",
                    url=url,
                    element="<title>",
                    context=title_text,
                ))
            elif len(title_text) > 60:
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="Title tag too long",
                    description=f"Title is {len(title_text)} characters. Search engines may truncate it.",
                    recommendation="Shorten the title to under 60 characters.",
                    url=url,
                    element="<title>",
                    context=title_text[:100] + "...",
                ))

        return issues

    def _check_meta_description(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for meta description issues."""
        issues = []
        meta_desc = soup.find("meta", attrs={"name": "description"})

        if not meta_desc:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title="Missing meta description",
                description="No meta description found. Search engines may generate one automatically.",
                recommendation="Add a compelling meta description between 150-160 characters.",
                url=url,
                element='<meta name="description">',
            ))
        else:
            content = meta_desc.get("content", "").strip()
            if not content:
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title="Empty meta description",
                    description="Meta description tag exists but has no content.",
                    recommendation="Add descriptive content to the meta description.",
                    url=url,
                    element='<meta name="description">',
                ))
            elif len(content) < 70:
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="Meta description too short",
                    description=f"Meta description is only {len(content)} characters.",
                    recommendation="Expand to 150-160 characters for better SERP display.",
                    url=url,
                    element='<meta name="description">',
                    context=content,
                ))
            elif len(content) > 160:
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="Meta description too long",
                    description=f"Meta description is {len(content)} characters and may be truncated.",
                    recommendation="Shorten to under 160 characters.",
                    url=url,
                    element='<meta name="description">',
                    context=content[:200] + "...",
                ))

        return issues

    def _check_h1(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for H1 tag issues."""
        issues = []
        h1_tags = soup.find_all("h1")

        if not h1_tags:
            issues.append(self._create_issue(
                severity=Severity.HIGH,
                title="Missing H1 tag",
                description="No H1 heading found. Every page should have exactly one H1.",
                recommendation="Add a descriptive H1 heading that matches the page's main topic.",
                url=url,
                element="<h1>",
            ))
        elif len(h1_tags) > 1:
            h1_texts = [h1.get_text(strip=True)[:50] for h1 in h1_tags]
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title="Multiple H1 tags",
                description=f"Found {len(h1_tags)} H1 tags. Best practice is to have exactly one.",
                recommendation="Keep only the most important H1 and change others to H2 or lower.",
                url=url,
                element="<h1>",
                context="; ".join(h1_texts),
            ))
        else:
            h1_text = h1_tags[0].get_text(strip=True)
            if len(h1_text) < 10:
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="H1 tag too short",
                    description="The H1 heading is very short and may not be descriptive enough.",
                    recommendation="Make the H1 more descriptive of the page content.",
                    url=url,
                    element="<h1>",
                    context=h1_text,
                ))

        return issues

    def _check_canonical(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for canonical URL issues."""
        issues = []
        canonical = soup.find("link", attrs={"rel": "canonical"})

        if not canonical:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title="Missing canonical URL",
                description="No canonical link tag found. This can lead to duplicate content issues.",
                recommendation='Add <link rel="canonical" href="..."> pointing to the preferred URL.',
                url=url,
                element='<link rel="canonical">',
            ))
        else:
            href = canonical.get("href", "").strip()
            if not href:
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title="Empty canonical URL",
                    description="Canonical tag exists but has no href value.",
                    recommendation="Add the preferred URL to the canonical tag's href attribute.",
                    url=url,
                    element='<link rel="canonical">',
                ))

        return issues

    def _check_structured_data(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for structured data (JSON-LD, microdata)."""
        issues = []

        # Check for JSON-LD
        json_ld_scripts = soup.find_all("script", attrs={"type": "application/ld+json"})

        # Check for microdata
        has_microdata = bool(soup.find(attrs={"itemscope": True}))

        if not json_ld_scripts and not has_microdata:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title="No structured data found",
                description="No JSON-LD or microdata structured data detected.",
                recommendation="Add schema.org structured data to help search engines understand your content.",
                url=url,
            ))
        else:
            # Validate JSON-LD if present
            for script in json_ld_scripts:
                try:
                    if script.string:
                        json.loads(script.string)
                except json.JSONDecodeError as e:
                    issues.append(self._create_issue(
                        severity=Severity.MEDIUM,
                        title="Invalid JSON-LD",
                        description=f"JSON-LD structured data contains invalid JSON: {e}",
                        recommendation="Fix the JSON syntax in the structured data.",
                        url=url,
                        element='<script type="application/ld+json">',
                    ))

        return issues

    def _check_open_graph(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for Open Graph tags."""
        issues = []

        og_tags = {
            "og:title": soup.find("meta", attrs={"property": "og:title"}),
            "og:description": soup.find("meta", attrs={"property": "og:description"}),
            "og:image": soup.find("meta", attrs={"property": "og:image"}),
            "og:url": soup.find("meta", attrs={"property": "og:url"}),
        }

        missing = [tag for tag, element in og_tags.items() if not element]

        if len(missing) == 4:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title="No Open Graph tags",
                description="No Open Graph meta tags found. Social media sharing will use defaults.",
                recommendation="Add og:title, og:description, og:image, and og:url tags.",
                url=url,
            ))
        elif missing:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title="Incomplete Open Graph tags",
                description=f"Missing Open Graph tags: {', '.join(missing)}",
                recommendation="Add the missing Open Graph tags for better social media previews.",
                url=url,
            ))

        return issues

    def _check_heading_hierarchy(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for proper heading hierarchy."""
        issues = []

        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        if not headings:
            return issues

        # Check for skipped levels
        levels = [int(h.name[1]) for h in headings]
        for i in range(1, len(levels)):
            if levels[i] > levels[i-1] + 1:
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="Skipped heading level",
                    description=f"Heading jumps from H{levels[i-1]} to H{levels[i]}, skipping a level.",
                    recommendation="Use sequential heading levels (H1 → H2 → H3) for proper hierarchy.",
                    url=url,
                    element=f"<h{levels[i]}>",
                    context=headings[i].get_text(strip=True)[:50],
                ))
                break  # Report only first occurrence

        return issues
