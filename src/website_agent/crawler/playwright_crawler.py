"""Playwright-based crawler with anti-bot stealth settings.

Primary crawler that handles JavaScript-rendered sites and evades bot detection.
"""

import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..config import CRAWLER_DELAY, CRAWLER_MAX_PAGES, CRAWLER_TIMEOUT, CRAWLER_USER_AGENT

logger = logging.getLogger(__name__)


class CrawlResult:
    """Result of crawling a single page."""

    def __init__(
        self,
        url: str,
        status_code: int,
        html: str = "",
        text: str = "",
        load_time_ms: float = 0.0,
        error: Optional[str] = None,
        final_url: Optional[str] = None,
    ):
        self.url = url  # Original requested URL
        self.final_url = final_url or url  # URL after redirects
        self.was_redirect = final_url is not None and final_url != url
        self.status_code = status_code
        self.html = html
        self.text = text
        self.load_time_ms = load_time_ms
        self.error = error
        self.crawled_at = datetime.utcnow()

    @property
    def soup(self) -> BeautifulSoup:
        """Parse HTML with BeautifulSoup."""
        return BeautifulSoup(self.html, "lxml")


class PlaywrightCrawler:
    """Playwright-based crawler with stealth settings for anti-bot evasion.

    Features:
    - JavaScript rendering
    - Anti-bot detection evasion
    - Screenshot capability
    - Rate limiting with randomized delays
    - Respects robots.txt
    """

    def __init__(
        self,
        base_url: str,
        max_pages: int = CRAWLER_MAX_PAGES,
        delay: float = CRAWLER_DELAY,
        timeout: int = CRAWLER_TIMEOUT,
        headless: bool = True,
        respect_robots: bool = True,
    ):
        """Initialize the crawler.

        Args:
            base_url: Starting URL to crawl
            max_pages: Maximum number of pages to crawl
            delay: Minimum delay between requests (seconds)
            timeout: Page load timeout (seconds)
            headless: Run browser in headless mode
            respect_robots: Whether to respect robots.txt
        """
        parsed = urlparse(base_url)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.start_url = base_url
        self.max_pages = max_pages
        self.delay = max(delay, 2.0)  # Minimum 2 seconds for anti-bot
        self.timeout = timeout * 1000  # Convert to ms
        self.headless = headless
        self.respect_robots = respect_robots

        self.visited: set[str] = set()
        self.to_visit: list[str] = [base_url]
        self.results: list[CrawlResult] = []
        self.disallowed_paths: set[str] = set()

        self._browser = None
        self._context = None
        self._playwright = None

    async def _init_browser(self):
        """Initialize Playwright browser with stealth settings."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        # Launch with stealth arguments
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )

        # Create context with realistic fingerprint
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=CRAWLER_USER_AGENT,
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="light",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )

        # Inject stealth scripts to hide automation
        await self._context.add_init_script("""
            // Hide webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Mock plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Mock languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Add chrome object
            window.chrome = { runtime: {} };
        """)

    async def _close_browser(self):
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _fetch_robots_txt(self):
        """Fetch and parse robots.txt for disallowed paths."""
        if not self.respect_robots:
            return

        robots_url = f"{self.base_url}/robots.txt"
        try:
            page = await self._context.new_page()
            response = await page.goto(robots_url, timeout=self.timeout)
            if response and response.status == 200:
                content = await page.content()
                # Simple robots.txt parsing - extract Disallow rules
                for line in content.split("\n"):
                    line = line.strip().lower()
                    if line.startswith("disallow:"):
                        path = line.split(":", 1)[1].strip()
                        if path:
                            self.disallowed_paths.add(path)
            await page.close()
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
        """Normalize URL by removing fragments and trailing slashes."""
        parsed = urlparse(url)
        # Remove fragment and normalize path
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def _extract_links(self, soup: BeautifulSoup, current_url: str) -> list[str]:
        """Extract all links from the page."""
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Skip javascript, mailto, tel links
            if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue

            # Convert relative to absolute
            full_url = urljoin(current_url, href)
            normalized = self._normalize_url(full_url)

            # Only include same-domain links
            if self._is_same_domain(normalized) and self._is_allowed(normalized):
                links.append(normalized)

        return links

    async def crawl_page(self, url: str, retry_count: int = 0) -> CrawlResult:
        """Crawl a single page and return the result.

        Uses a fallback strategy for page loading:
        1. First try 'domcontentloaded' (faster, more reliable)
        2. If that fails, retry with longer timeout
        3. Max 2 retries with exponential backoff
        """
        max_retries = 2
        page = await self._context.new_page()

        try:
            start_time = datetime.utcnow()

            # Use domcontentloaded instead of networkidle - more reliable for
            # Cloudflare/CDN sites that have persistent connections
            wait_strategy = "domcontentloaded"
            current_timeout = self.timeout * (1 + retry_count)  # Increase timeout on retry

            try:
                response = await page.goto(url, timeout=current_timeout, wait_until=wait_strategy)
            except Exception as nav_error:
                # If domcontentloaded fails, try with just 'commit' (earliest possible)
                if retry_count == 0:
                    logger.warning(f"Navigation failed with {wait_strategy}, trying 'commit': {url}")
                    try:
                        response = await page.goto(url, timeout=current_timeout * 2, wait_until="commit")
                        # Give extra time for content to load
                        await asyncio.sleep(2)
                    except Exception:
                        raise nav_error  # Re-raise original error
                else:
                    raise

            load_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

            # Get the final URL after any redirects
            final_url = page.url
            final_url_normalized = self._normalize_url(final_url)

            status_code = response.status if response else 0
            html = await page.content()

            # Extract visible text
            text = await page.evaluate("() => document.body.innerText")

            return CrawlResult(
                url=url,
                status_code=status_code,
                html=html,
                text=text or "",
                load_time_ms=load_time_ms,
                final_url=final_url_normalized if final_url_normalized != url else None,
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error crawling {url} (attempt {retry_count + 1}/{max_retries + 1}): {error_msg}")

            # Close this page before retry
            await page.close()

            # Retry logic with exponential backoff
            if retry_count < max_retries:
                wait_time = (retry_count + 1) * 5  # 5s, 10s
                logger.info(f"Retrying {url} in {wait_time}s...")
                await asyncio.sleep(wait_time)
                return await self.crawl_page(url, retry_count + 1)

            return CrawlResult(
                url=url,
                status_code=0,
                error=error_msg,
            )
        finally:
            if not page.is_closed():
                await page.close()

    async def crawl(self, progress_callback=None) -> list[CrawlResult]:
        """Crawl the website starting from base_url.

        Args:
            progress_callback: Optional callback(pages_done, pages_total, current_url)

        Returns:
            List of CrawlResult objects for each page.
        """
        await self._init_browser()

        # Track final URLs to avoid analyzing redirected duplicates
        final_urls_seen: set[str] = set()
        redirect_count = 0

        try:
            # Fetch robots.txt first
            await self._fetch_robots_txt()

            while self.to_visit and len(self.visited) < self.max_pages:
                url = self.to_visit.pop(0)

                if url in self.visited:
                    continue

                self.visited.add(url)

                if progress_callback:
                    progress_callback(len(self.visited), self.max_pages, url)

                logger.info(f"Crawling ({len(self.visited)}/{self.max_pages}): {url}")

                result = await self.crawl_page(url)

                # Check if this is a redirect to an already-analyzed page
                if result.was_redirect and result.final_url in final_urls_seen:
                    logger.info(f"Skipping duplicate (redirect): {url} -> {result.final_url}")
                    redirect_count += 1
                    # Don't add to results - it's a duplicate
                    continue

                # Track the final URL
                final_urls_seen.add(result.final_url)

                # Also add original URL pattern to visited to avoid re-crawling
                # (e.g., if we see node/123, don't queue it again)
                if result.was_redirect:
                    self.visited.add(result.final_url)
                    redirect_count += 1
                    logger.info(f"Redirect: {url} -> {result.final_url}")

                self.results.append(result)

                # Extract and queue new links
                if result.html and result.status_code == 200:
                    soup = result.soup
                    new_links = self._extract_links(soup, result.final_url)
                    for link in new_links:
                        if link not in self.visited and link not in self.to_visit:
                            self.to_visit.append(link)

                # Randomized delay between requests
                delay = self.delay + random.uniform(0.5, 1.5)
                await asyncio.sleep(delay)

            if redirect_count > 0:
                logger.info(f"Total redirects detected: {redirect_count}")

            return self.results

        finally:
            await self._close_browser()

    async def crawl_single(self, url: str) -> CrawlResult:
        """Crawl a single URL without following links.

        Useful for re-checking specific pages or API endpoints.
        """
        await self._init_browser()
        try:
            return await self.crawl_page(url)
        finally:
            await self._close_browser()
