import json
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo

import typer

from website_agent.analyzers import ContentAnalyzer, SEOAnalyzer
from website_agent.config import get_settings
from website_agent.crawler import SimpleCrawler
from website_agent.models import Issue, PageResult
from website_agent.reporting import Aggregator
from website_agent.storage import SQLiteStore

app = typer.Typer(help="Website Quality Agent CLI")


@app.command()
def scan(url: str, max_pages: int = typer.Option(None, help="Maximum pages to crawl"), rate_limit: float = None):
    """
    Crawl a site, run basic analyzers, and store results in SQLite.
    """
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    crawler = SimpleCrawler(rate_limit_seconds=rate_limit or settings.rate_limit_seconds, tz=tz)
    pages: List[PageResult] = crawler.crawl(url, max_pages=max_pages or settings.default_max_pages)

    analyzers = [SEOAnalyzer(), ContentAnalyzer()]
    issues: List[Issue] = []
    for page in pages:
        for analyzer in analyzers:
            issues.extend(analyzer.analyze(page))

    store = SQLiteStore(settings.database_path)
    created_at = pages[0].fetched_at.isoformat() if pages else datetime.now(tz).isoformat()
    scan_id = store.create_scan(url, created_at)
    page_ids = store.save_pages(scan_id, pages)
    page_lookup = {str(page.url): pid for page, pid in zip(pages, page_ids)}
    store.save_issues(scan_id, page_lookup, issues)

    summary = Aggregator().summarize(scan_id, url, pages, issues)
    typer.echo(json.dumps(summary.model_dump(), indent=2, default=str))
    typer.echo(f"Stored scan {scan_id} in {settings.database_path}")


def entrypoint():
    app()


if __name__ == "__main__":
    entrypoint()

