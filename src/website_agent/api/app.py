"""FastAPI web service for Website Quality Agent.

Provides REST API endpoints for:
- Starting new scans
- Checking scan status
- Retrieving scan results
- Viewing reports
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl

from ..config import API_HOST, API_PORT
from ..crawler import PlaywrightCrawler
from ..analyzers import (
    SEOAnalyzer,
    ContentAnalyzer,
    AccessibilityAnalyzer,
    LinkAnalyzer,
    PerformanceAnalyzer,
    MobileAnalyzer,
    ComplianceAnalyzer,
    CMSAnalyzer,
)
from ..models import IssueCategory, PageResult, ScanRequest, ScanResult, ScanStatus
from ..reporting import ReportAggregator
from ..storage import SQLiteStore

app = FastAPI(
    title="Website Quality Agent",
    description="Automated website quality analyzer",
    version="0.1.0",
)

# CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:8002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage and services
store = SQLiteStore()
aggregator = ReportAggregator()

# Analyzers
analyzers = [
    SEOAnalyzer(),
    ContentAnalyzer(),
    AccessibilityAnalyzer(),
    LinkAnalyzer(),
    PerformanceAnalyzer(),
    MobileAnalyzer(),
    ComplianceAnalyzer(),
    CMSAnalyzer(),
]


class ScanResponse(BaseModel):
    """Response for scan creation."""
    scan_id: str
    status: str
    message: str


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Website Quality Agent",
        "version": "0.1.0",
        "endpoints": {
            "POST /api/scan": "Start a new scan",
            "GET /api/scan/{scan_id}": "Get scan status",
            "GET /api/scan/{scan_id}/results": "Get full results",
            "GET /api/scan/{scan_id}/report": "Get HTML report",
            "GET /api/scans": "List recent scans",
        },
    }


@app.post("/api/scan", response_model=ScanResponse)
async def start_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    """Start a new website scan.

    The scan runs in the background. Use the returned scan_id to check status.
    """
    scan_id = str(uuid.uuid4())[:8]
    url = str(request.url)

    # Create scan record
    store.create_scan(scan_id, url)

    # Run scan in background
    background_tasks.add_task(run_scan, scan_id, url, request.max_pages)

    return ScanResponse(
        scan_id=scan_id,
        status="pending",
        message=f"Scan started. Check status at /api/scan/{scan_id}",
    )


@app.get("/api/scan/{scan_id}", response_model=ScanStatus)
async def get_scan_status(scan_id: str):
    """Get the status of a scan."""
    status = store.get_scan_status(scan_id)
    if not status:
        raise HTTPException(status_code=404, detail="Scan not found")
    return status


@app.get("/api/scan/{scan_id}/results")
async def get_scan_results(scan_id: str):
    """Get full scan results."""
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    return {
        "scan": scan.model_dump(),
        "issues_by_category": store.get_issues_by_category(scan_id),
    }


@app.get("/api/scan/{scan_id}/report", response_class=HTMLResponse)
async def get_scan_report(scan_id: str):
    """Get HTML report for a scan."""
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    if scan.status != "completed":
        raise HTTPException(status_code=400, detail="Scan not completed yet")

    summary = aggregator.aggregate(scan)
    html = aggregator.generate_html_report(scan, summary)
    return HTMLResponse(content=html)


@app.get("/api/scans")
async def list_scans(limit: int = 20):
    """List recent scans."""
    scans = store.list_scans(limit=limit)
    return {"scans": [s.model_dump() for s in scans]}


@app.delete("/api/scan/{scan_id}")
async def delete_scan(scan_id: str):
    """Delete a scan and its results."""
    status = store.get_scan_status(scan_id)
    if not status:
        raise HTTPException(status_code=404, detail="Scan not found")

    store.delete_scan(scan_id)
    return {"message": f"Scan {scan_id} deleted"}


async def run_scan(scan_id: str, url: str, max_pages: int):
    """Background task to run a website scan."""
    try:
        store.update_scan_status(scan_id, "running")

        # Crawl the site
        crawler = PlaywrightCrawler(url, max_pages=max_pages)
        crawl_results = await crawler.crawl()

        # Analyze each page
        pages = []
        for result in crawl_results:
            if result.status_code != 200:
                pages.append(PageResult(
                    url=result.url,
                    status_code=result.status_code,
                    load_time_ms=result.load_time_ms,
                    crawled_at=result.crawled_at,
                ))
                continue

            # Run all analyzers
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
                    print(f"Analyzer {analyzer.__class__.__name__} failed: {e}")

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

        # Create scan result and summary
        scan = ScanResult(
            id=scan_id,
            url=url,
            started_at=datetime.utcnow(),  # Approximate
            completed_at=datetime.utcnow(),
            status="completed",
            pages=pages,
        )

        summary = aggregator.aggregate(scan)
        store.update_scan_status(scan_id, "completed", summary=summary)

    except Exception as e:
        store.update_scan_status(scan_id, "failed", error=str(e))
        raise


def run_server():
    """Run the API server."""
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)


if __name__ == "__main__":
    run_server()
