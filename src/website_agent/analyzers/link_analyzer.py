"""Link analyzer for detecting broken links and related issues.

Checks for:
- Internal broken links (404s)
- External broken links
- 403 Forbidden errors
- Thin content pages
- Redirect chains
"""

import asyncio
import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..models import Issue, IssueCategory, Severity
from .base import BaseAnalyzer

logger = logging.getLogger(__name__)


class LinkAnalyzer(BaseAnalyzer):
    """Analyzer for link-related issues."""

    category = IssueCategory.LINKS

    # Browser-like headers to avoid bot detection
    BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Domains that block automated requests - collect but don't check
    MANUAL_CHECK_DOMAINS = [
        "twitter.com",
        "x.com",
        "instagram.com",
        "facebook.com",
        "linkedin.com",
        "clutch.co",
        "tiktok.com",
        "pinterest.com",
        "threads.net",
    ]

    def __init__(self, check_external: bool = False, timeout: float = 10.0):
        """Initialize link analyzer.

        Args:
            check_external: Whether to check external links (slower)
            timeout: Timeout for link checks in seconds
        """
        self.check_external = check_external
        self.timeout = timeout
        self._checked_links: dict[str, int] = {}  # Cache of checked links

    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[Issue]:
        """Analyze page for link issues.

        Note: For async link checking, use analyze_async instead.
        This sync version only checks for structural issues.
        """
        issues = []
        soup = self._get_soup(html, soup)

        # Check for common link issues
        issues.extend(self._check_empty_links(soup, url))
        issues.extend(self._check_javascript_links(soup, url))
        issues.extend(self._check_thin_content(text, url))

        return issues

    async def analyze_async(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
        base_url: Optional[str] = None,
    ) -> list[Issue]:
        """Async version that actually checks link status codes."""
        issues = []
        soup = self._get_soup(html, soup)

        # Get structural issues first
        issues.extend(self._check_empty_links(soup, url))
        issues.extend(self._check_javascript_links(soup, url))
        issues.extend(self._check_thin_content(text, url))

        # Now check actual links
        issues.extend(await self._check_links_async(soup, url, base_url))

        return issues

    def _check_empty_links(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for empty href attributes."""
        issues = []

        empty_links = soup.find_all("a", href="")
        if empty_links:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"Found {len(empty_links)} empty links",
                description="Links with empty href attributes don't navigate anywhere.",
                recommendation="Add valid href or remove the link.",
                url=url,
            ))

        return issues

    def _check_javascript_links(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for javascript: links."""
        issues = []

        js_links = soup.find_all("a", href=lambda x: x and x.startswith("javascript:"))
        for link in js_links[:5]:  # Report first 5
            href = link.get("href", "")
            if href == "javascript:void(0)" or href == "javascript:;":
                link_text = link.get_text(strip=True)[:30]
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="JavaScript-only link",
                    description="Link uses javascript: href which may not work if JavaScript is disabled.",
                    recommendation="Use a button element for actions, or provide a fallback href.",
                    url=url,
                    element=f'<a href="javascript:...">{link_text}</a>',
                ))

        return issues

    def _check_thin_content(self, text: str, url: str) -> list[Issue]:
        """Check for thin content pages."""
        issues = []

        word_count = len(text.split()) if text else 0

        if word_count < 50:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title="Thin content page",
                description=f"Page has only {word_count} words, which may indicate thin content.",
                recommendation="Add more substantial content or consider if this page is necessary.",
                url=url,
            ))

        return issues

    def _is_manual_check_domain(self, url: str) -> bool:
        """Check if URL is from a domain that blocks automated requests."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return any(d in domain for d in self.MANUAL_CHECK_DOMAINS)

    async def _check_links_async(
        self,
        soup: BeautifulSoup,
        page_url: str,
        base_url: Optional[str] = None,
    ) -> list[Issue]:
        """Check all links on the page for status codes."""
        issues = []
        manual_check_links = []  # Links that need manual review

        if base_url is None:
            parsed = urlparse(page_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

        links = soup.find_all("a", href=True)
        urls_to_check = []

        for link in links:
            href = link.get("href", "")

            # Skip non-HTTP links
            if href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
                continue

            # Convert relative to absolute
            full_url = urljoin(page_url, href)
            parsed = urlparse(full_url)

            # Determine if internal or external
            is_internal = parsed.netloc == urlparse(base_url).netloc

            # Check if this is a domain that blocks bots
            if not is_internal and self._is_manual_check_domain(full_url):
                link_text = link.get_text(strip=True)[:50]
                manual_check_links.append((full_url, link_text, page_url))
                continue

            if is_internal or self.check_external:
                urls_to_check.append((full_url, is_internal, link.get_text(strip=True)[:50]))

        # Check links in parallel with rate limiting
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.BROWSER_HEADERS,
        ) as client:
            tasks = []
            for full_url, is_internal, link_text in urls_to_check:
                # Skip if already checked
                if full_url in self._checked_links:
                    status = self._checked_links[full_url]
                    if status >= 400:
                        issues.append(self._create_link_issue(
                            full_url, status, is_internal, link_text, page_url
                        ))
                else:
                    tasks.append(self._check_single_link(client, full_url, is_internal, link_text, page_url))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Issue):
                    issues.append(result)

        # Add issues for links that need manual review (bot-blocking domains)
        for full_url, link_text, source_url in manual_check_links:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title=f"Manual check needed: {full_url[:60]}",
                description=(
                    f"This link is to a domain that blocks automated requests "
                    f"(social media, etc.). Please verify manually that the link works."
                ),
                recommendation="Open the link in a browser to verify it's not broken.",
                url=source_url,
                element=f'<a href="{full_url}">{link_text}</a>',
                context="Domain blocks automated checking",
            ))

        return issues

    async def _check_single_link(
        self,
        client: httpx.AsyncClient,
        url: str,
        is_internal: bool,
        link_text: str,
        source_url: str,
    ) -> Optional[Issue]:
        """Check a single link and return an issue if broken."""
        try:
            response = await client.head(url)
            status = response.status_code

            # Cache the result
            self._checked_links[url] = status

            if status >= 400:
                return self._create_link_issue(url, status, is_internal, link_text, source_url)

        except Exception as e:
            logger.debug(f"Error checking {url}: {e}")
            self._checked_links[url] = 0
            return self._create_issue(
                severity=Severity.MEDIUM if is_internal else Severity.LOW,
                title=f"Link unreachable: {url[:50]}",
                description=f"Could not connect to the linked URL: {e}",
                recommendation="Check if the URL is correct and the server is accessible.",
                url=source_url,
                context=link_text,
            )

        return None

    def _create_link_issue(
        self,
        broken_url: str,
        status: int,
        is_internal: bool,
        link_text: str,
        source_url: str,
    ) -> Issue:
        """Create an issue for a broken link."""
        severity = Severity.HIGH if is_internal else Severity.MEDIUM

        if status == 404:
            title = f"Broken link (404): {broken_url[:50]}"
            description = "Link returns 404 Not Found."
            recommendation = "Update or remove the broken link."
        elif status == 403:
            title = f"Forbidden link (403): {broken_url[:50]}"
            description = "Link returns 403 Forbidden, which may be exposed to users."
            recommendation = "Check if this link should be accessible or remove it."
        elif status == 500:
            title = f"Server error (500): {broken_url[:50]}"
            description = "Link returns a server error."
            recommendation = "Check the linked page for server-side issues."
        else:
            title = f"Link error ({status}): {broken_url[:50]}"
            description = f"Link returns HTTP {status}."
            recommendation = "Investigate and fix the linked resource."

        return self._create_issue(
            severity=severity,
            title=title,
            description=description,
            recommendation=recommendation,
            url=source_url,
            element=f'<a href="{broken_url}">{link_text}</a>',
            context=f"Status: {status}",
        )
