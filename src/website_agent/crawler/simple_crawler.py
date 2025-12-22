import time
from collections import deque
from datetime import tzinfo
from typing import List, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from website_agent.models import PageResult


class SimpleCrawler:
    """
    Lightweight crawler that follows same-domain links with polite rate limiting.
    This is a baseline implementation; swap with Playwright for JS-heavy sites later.
    """

    def __init__(
        self,
        rate_limit_seconds: float = 1.5,
        user_agent: str = "website-quality-agent/0.1",
        tz: tzinfo | None = None,
    ):
        self.rate_limit_seconds = rate_limit_seconds
        self.user_agent = user_agent
        self.tz = tz

    def crawl(self, start_url: str, max_pages: int = 25) -> List[PageResult]:
        visited: Set[str] = set()
        queue: deque[str] = deque([start_url])
        results: List[PageResult] = []
        parsed_root = urlparse(start_url)

        with httpx.Client(headers={"User-Agent": self.user_agent}, follow_redirects=True, timeout=15.0) as client:
            while queue and len(results) < max_pages:
                url = queue.popleft()
                if url in visited:
                    continue
                visited.add(url)

                try:
                    response = client.get(url)
                    content = response.text
                except Exception:
                    continue

                results.append(
                    PageResult(
                        url=url,
                        status_code=response.status_code,
                        content=content,
                        fetched_at=time_to_datetime(time.time(), tz=self.tz),
                    )
                )

                if response.status_code == 200 and content:
                    for link in self._extract_links(content, url, parsed_root):
                        if link not in visited and link not in queue:
                            queue.append(link)

                time.sleep(self.rate_limit_seconds)

        return results

    def _extract_links(self, html: str, base_url: str, parsed_root) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: List[str] = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme in {"http", "https"} and parsed.netloc == parsed_root.netloc:
                links.append(absolute.split("#")[0])
        return links


def time_to_datetime(ts: float, tz: tzinfo | None = None):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=tz or timezone.utc)

