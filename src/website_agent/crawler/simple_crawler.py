"""Simple requests-based crawler for fallback.

Faster than Playwright but doesn't handle JavaScript-rendered content.
Use as fallback when Playwright is unavailable or for simple static sites.
"""

import logging
import random
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..config import CRAWLER_DELAY, CRAWLER_MAX_PAGES, CRAWLER_TIMEOUT, CRAWLER_USER_AGENT
from .playwright_crawler import CrawlResult

logger = logging.getLogger(__name__)


class SimpleCrawler:
    """Simple requests-based crawler.

    Use this when:
    - Playwright is unavailable
    - Site doesn't require JavaScript
    - Speed is more important than completeness
    """

    def __init__(
        self,
        base_url: str,
        max_pages: int = CRAWLER_MAX_PAGES,
        delay: float = CRAWLER_DELAY,
        timeout: int = CRAWLER_TIMEOUT,
        respect_robots: bool = True,
    ):
        parsed = urlparse(base_url)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.start_url = base_url
        self.max_pages = max_pages
        self.delay = max(delay, 1.0)
        self.timeout = timeout
        self.respect_robots = respect_robots

        self.visited: set[str] = set()
        self.to_visit: list[str] = [base_url]
        self.results: list[CrawlResult] = []
        self.disallowed_paths: set[str] = set()

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": CRAWLER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })

    def _fetch_robots_txt(self):
        """Fetch and parse robots.txt."""
        if not self.respect_robots:
            return

        robots_url = f"{self.base_url}/robots.txt"
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
            if response.status_code == 200:
                for line in response.text.split("\n"):
                    line = line.strip().lower()
                    if line.startswith("disallow:"):
                        path = line.split(":", 1)[1].strip()
                        if path:
                            self.disallowed_paths.add(path)
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt: {e}")

    def _is_allowed(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt."""
        if not self.respect_robots or not self.disallowed_paths:
            return True

        parsed = urlparse(url)
        path = parsed.path or "/"

        for disallowed in self.disallowed_paths:
            if path.startswith(disallowed):
                return False
        return True

    def _is_same_domain(self, url: str) -> bool:
        """Check if URL is on the same domain."""
        parsed = urlparse(url)
        base_parsed = urlparse(self.base_url)
        return parsed.netloc == base_parsed.netloc

    def _normalize_url(self, url: str) -> str:
        """Normalize URL."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def _extract_links(self, soup: BeautifulSoup, current_url: str) -> list[str]:
        """Extract all links from the page."""
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue

            full_url = urljoin(current_url, href)
            normalized = self._normalize_url(full_url)

            if self._is_same_domain(normalized) and self._is_allowed(normalized):
                links.append(normalized)

        return links

    def _extract_text(self, soup: BeautifulSoup) -> str:
        """Extract visible text from HTML."""
        # Remove script and style elements
        for element in soup(["script", "style", "noscript"]):
            element.decompose()

        return soup.get_text(separator=" ", strip=True)

    def crawl_page(self, url: str) -> CrawlResult:
        """Crawl a single page."""
        try:
            start_time = datetime.utcnow()
            response = self.session.get(url, timeout=self.timeout)
            load_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

            soup = BeautifulSoup(response.text, "lxml")
            text = self._extract_text(soup)

            return CrawlResult(
                url=url,
                status_code=response.status_code,
                html=response.text,
                text=text,
                load_time_ms=load_time_ms,
            )
        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
            return CrawlResult(
                url=url,
                status_code=0,
                error=str(e),
            )

    def crawl(self, progress_callback=None) -> list[CrawlResult]:
        """Crawl the website."""
        self._fetch_robots_txt()

        while self.to_visit and len(self.visited) < self.max_pages:
            url = self.to_visit.pop(0)

            if url in self.visited:
                continue

            self.visited.add(url)

            if progress_callback:
                progress_callback(len(self.visited), self.max_pages, url)

            logger.info(f"Crawling ({len(self.visited)}/{self.max_pages}): {url}")

            result = self.crawl_page(url)
            self.results.append(result)

            if result.html and result.status_code == 200:
                soup = BeautifulSoup(result.html, "lxml")
                new_links = self._extract_links(soup, url)
                for link in new_links:
                    if link not in self.visited and link not in self.to_visit:
                        self.to_visit.append(link)

            # Delay between requests
            delay = self.delay + random.uniform(0.2, 0.8)
            time.sleep(delay)

        return self.results

    def crawl_single(self, url: str) -> CrawlResult:
        """Crawl a single URL without following links."""
        return self.crawl_page(url)
