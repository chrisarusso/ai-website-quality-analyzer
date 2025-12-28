"""Command-line interface for Website Quality Agent.

Usage:
    website-agent scan <url> [--max-pages N] [--output FORMAT]
    website-agent status <scan_id>
    website-agent report <scan_id> [--format html|text]
    website-agent list
    website-agent serve
"""

import argparse
import asyncio
import re
import sys
import uuid
from datetime import datetime
from urllib.parse import urlparse

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .config import API_PORT
from .crawler import PlaywrightCrawler
from .slack import notify_scan_started, notify_scan_completed, notify_scan_failed
from .analyzers import (
    SEOAnalyzer,
    ContentAnalyzer,
    AccessibilityAnalyzer,
    LinkAnalyzer,
    PerformanceAnalyzer,
    MobileAnalyzer,
    ComplianceAnalyzer,
    CMSAnalyzer,
)
from .models import PageResult, ScanResult
from .reporting import ReportAggregator
from .storage import SQLiteStore

console = Console()


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        prog="website-agent",
        description="Website Quality Agent - Automated website quality analyzer",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Scan a website")
    scan_parser.add_argument("url", help="URL to scan")
    scan_parser.add_argument(
        "--max-pages", "-m", type=int, default=20,
        help="Maximum pages to crawl (default: 20, use 0 for unlimited)"
    )
    scan_parser.add_argument(
        "--all", "-a", action="store_true",
        help="Crawl all pages (no limit)"
    )
    scan_parser.add_argument(
        "--output", "-o", choices=["text", "html", "json"], default="text",
        help="Output format (default: text)"
    )

    # status command
    status_parser = subparsers.add_parser("status", help="Check scan status")
    status_parser.add_argument("scan_id", help="Scan ID to check")

    # report command
    report_parser = subparsers.add_parser("report", help="View scan report")
    report_parser.add_argument("scan_id", help="Scan ID")
    report_parser.add_argument(
        "--format", "-f", choices=["text", "html"], default="text",
        help="Report format (default: text)"
    )

    # list command
    subparsers.add_parser("list", help="List recent scans")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start API server")
    serve_parser.add_argument(
        "--port", "-p", type=int, default=API_PORT,
        help=f"Port to listen on (default: {API_PORT})"
    )

    return parser


class ScanError(Exception):
    """Exception raised when scan encounters a critical error."""
    pass


def url_to_filename_slug(url: str) -> str:
    """Convert URL to a clean filename-safe slug.

    Examples:
        https://savaslabs.com -> savaslabs
        https://americanpackaging.com -> americanpackaging
        https://www.example.com/path -> example
    """
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path

    # Remove www. prefix
    if domain.startswith("www."):
        domain = domain[4:]

    # Get just the main domain name (before any dots for TLD)
    parts = domain.split(".")
    if len(parts) >= 2:
        # Take the main name (e.g., "savaslabs" from "savaslabs.com")
        name = parts[0]
    else:
        name = domain

    # Clean up any remaining non-alphanumeric chars
    name = re.sub(r"[^a-zA-Z0-9]", "", name)

    # Truncate if too long
    return name[:20].lower() if name else "site"


async def run_scan(url: str, max_pages: int) -> ScanResult:
    """Run a website scan."""
    scan_id = str(uuid.uuid4())[:8]
    store = SQLiteStore()
    aggregator = ReportAggregator()

    # Initialize analyzers
    # LinkAnalyzer is handled separately for async link checking
    link_analyzer = LinkAnalyzer(check_external=True)
    analyzers = [
        SEOAnalyzer(),
        ContentAnalyzer(),
        AccessibilityAnalyzer(),
        PerformanceAnalyzer(),
        MobileAnalyzer(),
        ComplianceAnalyzer(),
        CMSAnalyzer(),
    ]

    store.create_scan(scan_id, url)
    store.update_scan_status(scan_id, "running")

    pages = []
    started_at = datetime.utcnow()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Crawl phase
        task = progress.add_task("Crawling website...", total=None)

        crawler = PlaywrightCrawler(url, max_pages=max_pages)

        def update_progress(done, total, current_url):
            progress.update(task, description=f"Crawling ({done}/{total}): {current_url[:50]}...")

        crawl_results = await crawler.crawl(progress_callback=update_progress)
        progress.update(task, description=f"Crawled {len(crawl_results)} pages")

        # ===== EARLY ERROR DETECTION =====
        # Check if the homepage (first/primary page) failed - this is critical
        if crawl_results:
            first_result = crawl_results[0]
            if first_result.error or first_result.status_code == 0:
                error_msg = first_result.error or "Unknown error - page returned no content"
                console.print(f"\n[red bold]CRITICAL ERROR: Failed to load homepage[/red bold]")
                console.print(f"[red]URL: {url}[/red]")
                console.print(f"[red]Error: {error_msg}[/red]")
                console.print(f"\n[yellow]This usually means:[/yellow]")
                console.print("  - The site is blocking automated requests")
                console.print("  - The site is behind a firewall or requires authentication")
                console.print("  - The site is down or unreachable")
                console.print("  - There's a network/DNS issue")
                store.update_scan_status(scan_id, "failed", error=f"Homepage failed: {error_msg}")
                raise ScanError(f"Failed to load homepage: {error_msg}")

        # Check if we got very few pages (potential blocking)
        successful_pages = [r for r in crawl_results if r.status_code == 200]
        failed_pages = [r for r in crawl_results if r.status_code == 0 or r.error]

        if len(crawl_results) > 0:
            failure_rate = len(failed_pages) / len(crawl_results)
            if failure_rate > 0.5 and len(failed_pages) > 3:
                console.print(f"\n[yellow]WARNING: High failure rate detected[/yellow]")
                console.print(f"[yellow]  {len(failed_pages)}/{len(crawl_results)} pages failed to load ({failure_rate:.0%})[/yellow]")
                console.print(f"[yellow]  The site may be rate-limiting or blocking requests[/yellow]\n")

        if len(successful_pages) == 0:
            error_msg = "No pages could be loaded successfully"
            console.print(f"\n[red bold]CRITICAL ERROR: {error_msg}[/red bold]")
            store.update_scan_status(scan_id, "failed", error=error_msg)
            raise ScanError(error_msg)

        console.print(f"\n[green]Successfully crawled {len(successful_pages)} pages[/green]")
        if failed_pages:
            console.print(f"[yellow]  ({len(failed_pages)} pages failed to load)[/yellow]")
        # ===== END EARLY ERROR DETECTION =====

        # Analysis phase
        progress.update(task, description="Analyzing pages...")

        for result in crawl_results:
            if result.status_code != 200:
                pages.append(PageResult(
                    url=result.url,
                    status_code=result.status_code,
                    load_time_ms=result.load_time_ms,
                    crawled_at=result.crawled_at,
                ))
                continue

            all_issues = []
            soup = result.soup

            for analyzer in analyzers:
                try:
                    issues = analyzer.analyze(
                        url=result.url,
                        html=result.html,
                        text=result.text,
                        soup=soup,
                    )
                    all_issues.extend(issues)
                except Exception as e:
                    console.print(f"[yellow]Warning: {analyzer.__class__.__name__} failed: {e}[/yellow]")

            # Run async link checking (checks actual link status codes)
            try:
                link_issues = await link_analyzer.analyze_async(
                    url=result.url,
                    html=result.html,
                    text=result.text,
                    soup=soup,
                    base_url=url,
                )
                all_issues.extend(link_issues)
            except Exception as e:
                console.print(f"[yellow]Warning: LinkAnalyzer failed: {e}[/yellow]")

            # Extract metadata
            title = soup.find("title")
            title_text = title.string.strip() if title and title.string else None

            meta_desc = soup.find("meta", attrs={"name": "description"})
            meta_desc_text = meta_desc.get("content", "").strip() if meta_desc else None

            h1_tags = [h1.get_text(strip=True) for h1 in soup.find_all("h1")]

            page = PageResult(
                url=result.url,
                status_code=result.status_code,
                title=title_text,
                meta_description=meta_desc_text,
                h1_tags=h1_tags,
                word_count=len(result.text.split()) if result.text else 0,
                load_time_ms=result.load_time_ms,
                issues=all_issues,
                crawled_at=result.crawled_at,
            )

            pages.append(page)
            store.save_page(scan_id, page)

        progress.update(task, description="Generating report...")

    # Create scan result
    scan = ScanResult(
        id=scan_id,
        url=url,
        started_at=started_at,
        completed_at=datetime.utcnow(),
        status="completed",
        pages=pages,
    )

    summary = aggregator.aggregate(scan)
    store.update_scan_status(scan_id, "completed", summary=summary)
    scan.summary = summary

    return scan


def cmd_scan(args):
    """Handle scan command."""
    import time

    # Handle unlimited crawling
    max_pages = args.max_pages
    if args.all or max_pages == 0:
        max_pages = 999999  # Effectively unlimited
        console.print(f"\n[bold]Scanning:[/bold] {args.url}")
        console.print(f"[dim]Max pages: unlimited[/dim]\n")
    else:
        console.print(f"\n[bold]Scanning:[/bold] {args.url}")
        console.print(f"[dim]Max pages: {max_pages}[/dim]\n")

    # Generate scan ID early so we can use it in notifications
    scan_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    # Send Slack notification for scan start
    notify_scan_started(args.url, max_pages, scan_id)

    try:
        scan = asyncio.run(run_scan(args.url, max_pages))
        duration_seconds = int(time.time() - start_time)

        report_filename = None
        if args.output == "text":
            aggregator = ReportAggregator()
            report = aggregator.generate_text_report(scan, scan.summary)
            console.print(report)
        elif args.output == "html":
            aggregator = ReportAggregator()
            html = aggregator.generate_html_report(scan, scan.summary)
            # Generate filename with URL slug and timestamp
            url_slug = url_to_filename_slug(args.url)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            report_filename = f"report_{url_slug}_{timestamp}_{scan.id}.html"
            with open(report_filename, "w") as f:
                f.write(html)
            console.print(f"\n[green]HTML report saved to: {report_filename}[/green]")
        else:
            import json
            print(scan.model_dump_json(indent=2))

        console.print(f"\n[dim]Scan ID: {scan.id}[/dim]")

        # Send Slack notification for scan completion
        notify_scan_completed(
            url=args.url,
            scan_id=scan.id,
            pages_crawled=len(scan.pages),
            total_issues=scan.summary.total_issues if scan.summary else 0,
            overall_score=scan.summary.overall_score if scan.summary else 0,
            duration_seconds=duration_seconds,
            report_file=report_filename,
        )

    except Exception as e:
        duration_seconds = int(time.time() - start_time)
        # Send Slack notification for scan failure
        notify_scan_failed(
            url=args.url,
            scan_id=scan_id,
            error=str(e),
            duration_seconds=duration_seconds,
        )
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def cmd_status(args):
    """Handle status command."""
    store = SQLiteStore()
    status = store.get_scan_status(args.scan_id)

    if not status:
        console.print(f"[red]Scan not found: {args.scan_id}[/red]")
        sys.exit(1)

    table = Table(title=f"Scan Status: {args.scan_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("URL", status.url)
    table.add_row("Status", status.status)
    table.add_row("Pages Crawled", str(status.pages_crawled))
    table.add_row("Issues Found", str(status.issues_found))
    table.add_row("Started", status.started_at.strftime("%Y-%m-%d %H:%M:%S"))
    if status.completed_at:
        table.add_row("Completed", status.completed_at.strftime("%Y-%m-%d %H:%M:%S"))
    if status.error:
        table.add_row("Error", status.error)

    console.print(table)


def cmd_report(args):
    """Handle report command."""
    store = SQLiteStore()
    scan = store.get_scan(args.scan_id)

    if not scan:
        console.print(f"[red]Scan not found: {args.scan_id}[/red]")
        sys.exit(1)

    aggregator = ReportAggregator()
    summary = aggregator.aggregate(scan)

    if args.format == "html":
        html = aggregator.generate_html_report(scan, summary)
        filename = f"report_{scan.id}.html"
        with open(filename, "w") as f:
            f.write(html)
        console.print(f"[green]HTML report saved to: {filename}[/green]")
    else:
        report = aggregator.generate_text_report(scan, summary)
        console.print(report)


def cmd_list(args):
    """Handle list command."""
    store = SQLiteStore()
    scans = store.list_scans()

    if not scans:
        console.print("[dim]No scans found[/dim]")
        return

    table = Table(title="Recent Scans")
    table.add_column("ID", style="cyan")
    table.add_column("URL")
    table.add_column("Status")
    table.add_column("Started")

    for scan in scans:
        table.add_row(
            scan.id,
            scan.url[:50] + "..." if len(scan.url) > 50 else scan.url,
            scan.status,
            scan.started_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


def cmd_serve(args):
    """Handle serve command."""
    console.print(f"[bold]Starting API server on port {args.port}...[/bold]")

    import uvicorn
    from .api import app

    uvicorn.run(app, host="0.0.0.0", port=args.port)


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "scan": cmd_scan,
        "status": cmd_status,
        "report": cmd_report,
        "list": cmd_list,
        "serve": cmd_serve,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
