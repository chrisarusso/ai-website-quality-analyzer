from datetime import datetime
import json
from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from website_agent.config import get_settings
from website_agent.reporting.aggregator import Aggregator
from website_agent.storage.sqlite_store import SQLiteStore
from website_agent.models import Issue, PageResult, ScanSummary, Severity


def get_store():
    settings = get_settings()
    return SQLiteStore(settings.database_path)


def create_app() -> FastAPI:
    app = FastAPI(title="Website Quality Agent", version="0.1.0")
    template_dir = Path(__file__).parent.parent / "reporting" / "templates"
    templates = Jinja2Templates(directory=str(template_dir))
    aggregator = Aggregator()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, store: SQLiteStore = Depends(get_store)):
        rows = store.list_scans()
        scans = [
            {"id": r[0], "root_url": r[1], "created_at": r[2], "page_count": "-", "issue_count": "-"}
            for r in rows
        ]
        return templates.TemplateResponse("index.html", {"request": request, "scans": scans, "title": "Scans"})

    @app.get("/scans/{scan_id}", response_class=HTMLResponse)
    def scan_detail(scan_id: int, request: Request, store: SQLiteStore = Depends(get_store)):
        scan = store.get_scan(scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        pages_raw = store.get_pages(scan_id)
        issues_raw = store.get_issues(scan_id)

        pages: List[PageResult] = [
            PageResult(url=row[1], status_code=row[2], content=None, fetched_at=datetime.fromisoformat(row[3]))
            for row in pages_raw
        ]
        issues: List[Issue] = []
        for row in issues_raw:
            raw_meta = row[4]
            meta = {}
            if raw_meta:
                try:
                    meta = json.loads(raw_meta)
                except Exception:
                    meta = {}
            issues.append(
                Issue(category=row[0], severity=Severity(row[1]), message=row[2], location=row[3], meta=meta)
            )

        summary: ScanSummary = aggregator.summarize(scan_id, scan[1], pages, issues)
        return templates.TemplateResponse(
            "scan_detail.html",
            {"request": request, "scan_id": scan_id, "summary": summary, "pages": pages, "issues": issues},
        )

    return app

