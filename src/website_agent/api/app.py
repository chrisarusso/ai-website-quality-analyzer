"""FastAPI web service for Website Quality Agent.

Provides REST API endpoints for:
- Starting new scans
- Checking scan status
- Retrieving scan results
- Viewing reports
"""

import asyncio
import secrets
import uuid
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, HttpUrl
from starlette.middleware.sessions import SessionMiddleware

from ..config import (
    API_HOST, API_PORT, GITHUB_TOKEN, GITHUB_DEFAULT_REPO,
    API_USERNAME, API_PASSWORD, GOOGLE_CLIENT_ID, SESSION_SECRET_KEY,
)
from ..slack import notify_scan_started, notify_scan_completed, notify_scan_failed
from .auth import (
    login as auth_login,
    callback as auth_callback,
    logout as auth_logout,
    get_current_user,
    require_auth,
    get_login_url,
)
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
from ..models import (
    IssueCategory,
    PageResult,
    ScanRequest,
    ScanResult,
    ScanStatus,
    FixRequest,
    FixResponse,
    FixStatus,
    ProposedFix,
)
from ..fixer import FixClassifier, FixOrchestrator
from ..reporting import ReportAggregator
from ..storage import SQLiteStore

class AuthRedirectException(Exception):
    """Exception that signals a redirect to login is needed."""
    pass


app = FastAPI(
    title="Website Quality Agent",
    description="Automated website quality analyzer",
    version="0.1.0",
)

# Session middleware for OAuth (must be added before CORS)
session_secret = SESSION_SECRET_KEY or secrets.token_hex(32)
app.add_middleware(SessionMiddleware, secret_key=session_secret)


# Get path prefix from API_BASE_URL (e.g., "/website-quality-agent" from "https://internal.savaslabs.com/website-quality-agent")
def get_path_prefix():
    """Extract path prefix from API_BASE_URL."""
    from urllib.parse import urlparse
    from ..config import API_BASE_URL
    if API_BASE_URL:
        parsed = urlparse(API_BASE_URL)
        if parsed.path and parsed.path != '/':
            return parsed.path.rstrip('/')
    return ""

PATH_PREFIX = get_path_prefix()


# Exception handler for auth redirect
@app.exception_handler(AuthRedirectException)
async def auth_redirect_handler(request: Request, exc: AuthRedirectException):
    """Redirect unauthenticated browser requests to login page."""
    login_url = f"{PATH_PREFIX}/auth/login"
    return RedirectResponse(url=login_url, status_code=302)

# CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:8002", "http://localhost:8003"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional HTTP Basic Auth
security = HTTPBasic(auto_error=False)


def verify_auth(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
):
    """Verify authentication via Google OAuth session or HTTP Basic Auth.

    Priority:
    1. Check for valid Google OAuth session
    2. Fall back to HTTP Basic Auth (for API clients like curl)
    3. If neither, require authentication (redirect browsers to login)
    """
    # Check Google OAuth session first
    user = get_current_user(request)
    if user:
        return user

    # Fall back to HTTP Basic Auth if configured
    if API_USERNAME and API_PASSWORD and credentials:
        is_valid_username = secrets.compare_digest(
            credentials.username.encode("utf8"),
            API_USERNAME.encode("utf8")
        )
        is_valid_password = secrets.compare_digest(
            credentials.password.encode("utf8"),
            API_PASSWORD.encode("utf8")
        )
        if is_valid_username and is_valid_password:
            return {"email": "api-user", "name": "API User"}

    # No valid auth found - check if any auth is configured
    auth_configured = GOOGLE_CLIENT_ID or (API_USERNAME and API_PASSWORD)

    if not auth_configured:
        # No auth configured at all - allow access (dev mode)
        return {"email": "anonymous", "name": "Anonymous (dev mode)"}

    # Check if this is a browser request (wants HTML)
    accept_header = request.headers.get("accept", "")
    is_browser = "text/html" in accept_header

    # Auth is configured but not provided
    if GOOGLE_CLIENT_ID and is_browser:
        # Browser request - redirect to login
        raise AuthRedirectException()
    elif GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Visit /auth/login to sign in with Google.",
            headers={"WWW-Authenticate": "Basic"},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

# Storage and services
store = SQLiteStore()
aggregator = ReportAggregator()
fix_classifier = FixClassifier()
fix_orchestrator = FixOrchestrator(store=store)

# Analyzers
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


class ScanResponse(BaseModel):
    """Response for scan creation."""
    scan_id: str
    status: str
    message: str


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, auth: dict = Depends(verify_auth)):
    """Dashboard showing all scans with ability to start new ones."""
    user = auth if isinstance(auth, dict) else {}
    user_email = user.get("email", "Unknown")

    # Get all scans
    scans = store.list_scans(limit=50)

    # Build scan rows
    scan_rows = ""
    for scan in scans:
        status_class = {
            "completed": "status-completed",
            "running": "status-running",
            "pending": "status-pending",
            "failed": "status-failed",
        }.get(scan.status, "")

        # Format dates
        started = scan.started_at.strftime("%Y-%m-%d %H:%M") if scan.started_at else "-"

        # Score and issue count - get from full scan summary
        score = "-"
        issue_count = "-"
        if scan.status == "completed":
            full_scan = store.get_scan(scan.id)
            if full_scan and full_scan.summary:
                score = f"{full_scan.summary.overall_score:.0f}"
                issue_count = full_scan.summary.total_issues

        scan_rows += f"""
        <tr>
            <td><a href="{PATH_PREFIX}/api/scan/{scan.id}/report" class="scan-link">{scan.id}</a></td>
            <td class="url-cell"><a href="{scan.url}" target="_blank">{scan.url}</a></td>
            <td><span class="status {status_class}">{scan.status}</span></td>
            <td>{score}</td>
            <td>{issue_count}</td>
            <td>{started}</td>
            <td>
                <a href="{PATH_PREFIX}/api/scan/{scan.id}/report" class="btn btn-sm">Report</a>
                <button onclick="deleteScan('{scan.id}')" class="btn btn-sm btn-danger">Delete</button>
            </td>
        </tr>
        """

    if not scan_rows:
        scan_rows = '<tr><td colspan="7" class="no-scans">No scans yet. Start one below!</td></tr>'

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Website Quality Agent - Dashboard</title>
        <style>
            * {{ box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background: #f5f5f5;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 30px;
                padding: 20px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }}
            .header h1 {{ margin: 0; color: #333; }}
            .user-info {{
                display: flex;
                align-items: center;
                gap: 15px;
            }}
            .user-email {{ color: #666; }}
            .logout-btn {{
                padding: 8px 16px;
                background: #dc3545;
                color: white;
                text-decoration: none;
                border-radius: 4px;
            }}
            .logout-btn:hover {{ background: #c82333; }}

            .card {{
                background: white;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }}
            .card h2 {{
                margin-top: 0;
                color: #333;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
            }}

            .new-scan-form {{
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }}
            .new-scan-form input[type="url"] {{
                flex: 1;
                min-width: 300px;
                padding: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 16px;
            }}
            .new-scan-form input[type="number"] {{
                width: 100px;
                padding: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 16px;
            }}
            .btn {{
                padding: 12px 24px;
                background: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
                text-decoration: none;
                display: inline-block;
            }}
            .btn:hover {{ background: #0056b3; }}
            .btn-sm {{ padding: 6px 12px; font-size: 14px; }}
            .btn-danger {{ background: #dc3545; }}
            .btn-danger:hover {{ background: #c82333; }}

            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #eee;
            }}
            th {{
                background: #f8f9fa;
                font-weight: 600;
                color: #333;
            }}
            tr:hover {{ background: #f8f9fa; }}

            .status {{
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 500;
                text-transform: uppercase;
            }}
            .status-completed {{ background: #d4edda; color: #155724; }}
            .status-running {{ background: #fff3cd; color: #856404; }}
            .status-pending {{ background: #e2e3e5; color: #383d41; }}
            .status-failed {{ background: #f8d7da; color: #721c24; }}

            .url-cell {{
                max-width: 300px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .url-cell a {{ color: #007bff; text-decoration: none; }}
            .url-cell a:hover {{ text-decoration: underline; }}

            .scan-link {{ color: #007bff; text-decoration: none; font-family: monospace; }}
            .scan-link:hover {{ text-decoration: underline; }}

            .no-scans {{
                text-align: center;
                color: #666;
                padding: 40px !important;
            }}

            #scan-status {{
                margin-top: 15px;
                padding: 10px;
                border-radius: 4px;
                display: none;
            }}
            #scan-status.success {{ display: block; background: #d4edda; color: #155724; }}
            #scan-status.error {{ display: block; background: #f8d7da; color: #721c24; }}
            #scan-status.info {{ display: block; background: #cce5ff; color: #004085; }}
        </style>
    </head>
    <body>
        <nav style="padding: 10px 20px; background: #f8f9fa; border-bottom: 1px solid #dee2e6;">
            <a href="/" style="color: #007bff; text-decoration: none;">← Internal Tools</a>
        </nav>
        <div class="header">
            <h1>Website Quality Agent</h1>
            <div class="user-info">
                <span class="user-email">{user_email}</span>
                <a href="{PATH_PREFIX}/auth/logout" class="logout-btn">Logout</a>
            </div>
        </div>

        <div class="card">
            <h2>Start New Scan</h2>
            <form class="new-scan-form" onsubmit="startScan(event)">
                <input type="url" id="scan-url" placeholder="https://example.com" required>
                <input type="number" id="max-pages" value="50" min="1" max="9999" title="Max pages to crawl">
                <button type="submit" class="btn">Start Scan</button>
            </form>
            <div id="scan-status"></div>
        </div>

        <div class="card">
            <h2>Recent Scans</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>URL</th>
                        <th>Status</th>
                        <th>Score</th>
                        <th>Issues</th>
                        <th>Started</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {scan_rows}
                </tbody>
            </table>
        </div>

        <script>
            const API_PREFIX = '{PATH_PREFIX}';

            async function startScan(e) {{
                e.preventDefault();
                const url = document.getElementById('scan-url').value;
                const maxPages = parseInt(document.getElementById('max-pages').value) || 50;
                const statusDiv = document.getElementById('scan-status');

                statusDiv.className = 'info';
                statusDiv.textContent = 'Starting scan...';
                statusDiv.style.display = 'block';

                try {{
                    const response = await fetch(API_PREFIX + '/api/scan', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ url: url, max_pages: maxPages }})
                    }});

                    const data = await response.json();

                    if (response.ok) {{
                        statusDiv.className = 'success';
                        statusDiv.innerHTML = `Scan started! ID: <strong>${{data.scan_id}}</strong>. <a href="javascript:location.reload()">Refresh</a> to see progress.`;
                        document.getElementById('scan-url').value = '';
                    }} else {{
                        statusDiv.className = 'error';
                        statusDiv.textContent = data.detail || 'Failed to start scan';
                    }}
                }} catch (err) {{
                    statusDiv.className = 'error';
                    statusDiv.textContent = 'Error: ' + err.message;
                }}
            }}

            async function deleteScan(scanId) {{
                if (!confirm('Delete scan ' + scanId + '?')) return;

                try {{
                    const response = await fetch(API_PREFIX + '/api/scan/' + scanId, {{ method: 'DELETE' }});
                    if (response.ok) {{
                        location.reload();
                    }} else {{
                        const data = await response.json();
                        alert(data.detail || 'Failed to delete scan');
                    }}
                }} catch (err) {{
                    alert('Error: ' + err.message);
                }}
            }}

            // Auto-refresh for running scans
            const hasRunning = document.querySelector('.status-running');
            if (hasRunning) {{
                setTimeout(() => location.reload(), 10000);
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# =============================================================================
# Authentication Routes
# =============================================================================


@app.get("/auth/login")
async def login(request: Request):
    """Redirect to Google OAuth login."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    return await auth_login(request)


@app.get("/auth/callback")
async def callback(request: Request):
    """Handle Google OAuth callback."""
    return await auth_callback(request)


@app.get("/auth/logout")
async def logout(request: Request):
    """Clear session and logout."""
    return await auth_logout(request)


@app.get("/auth/me")
async def get_me(request: Request):
    """Get current user info."""
    user = get_current_user(request)
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "user": user}


@app.post("/api/scan", response_model=ScanResponse)
async def start_scan(
    scan_request: ScanRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    auth: dict = Depends(verify_auth),
):
    """Start a new website scan.

    The scan runs in the background. Use the returned scan_id to check status.

    Two modes:
    - Single URL mode: Provide `url` to crawl from that starting point
    - Multi-URL mode: Provide `urls` list to scan specific pages only (no crawling)
    """
    scan_id = str(uuid.uuid4())[:8]

    # Determine mode: multi-URL or single URL crawl
    if scan_request.urls:
        # Multi-URL mode: scan specific pages only
        urls = [str(u) for u in scan_request.urls]
        primary_url = urls[0]  # Use first URL as the scan's primary URL
        store.create_scan(scan_id, primary_url)
        background_tasks.add_task(run_multi_url_scan, scan_id, urls)
        return ScanResponse(
            scan_id=scan_id,
            status="pending",
            message=f"Scanning {len(urls)} specific URL(s). Check status at /api/scan/{scan_id}",
        )
    elif scan_request.url:
        # Single URL mode: crawl from starting point
        url = str(scan_request.url)
        store.create_scan(scan_id, url)
        background_tasks.add_task(run_scan, scan_id, url, scan_request.max_pages)
        return ScanResponse(
            scan_id=scan_id,
            status="pending",
            message=f"Scan started. Check status at /api/scan/{scan_id}",
        )
    else:
        raise HTTPException(status_code=400, detail="Must provide either 'url' or 'urls'")


@app.get("/api/scan/{scan_id}", response_model=ScanStatus)
async def get_scan_status(scan_id: str, request: Request, auth: dict = Depends(verify_auth)):
    """Get the status of a scan."""
    scan_status = store.get_scan_status(scan_id)
    if not scan_status:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan_status


@app.get("/api/scan/{scan_id}/results")
async def get_scan_results(scan_id: str, request: Request, auth: dict = Depends(verify_auth)):
    """Get full scan results."""
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    return {
        "scan": scan.model_dump(),
        "issues_by_category": store.get_issues_by_category(scan_id),
    }


@app.get("/api/scan/{scan_id}/report", response_class=HTMLResponse)
async def get_scan_report(scan_id: str, request: Request, auth: dict = Depends(verify_auth)):
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
async def list_scans(limit: int = 20, request: Request = None, auth: dict = Depends(verify_auth)):
    """List recent scans."""
    scans = store.list_scans(limit=limit)
    return {"scans": [s.model_dump() for s in scans]}


@app.delete("/api/scan/{scan_id}")
async def delete_scan(scan_id: str, request: Request, auth: dict = Depends(verify_auth)):
    """Delete a scan and its results."""
    status = store.get_scan_status(scan_id)
    if not status:
        raise HTTPException(status_code=404, detail="Scan not found")

    store.delete_scan(scan_id)
    return {"message": f"Scan {scan_id} deleted"}


# =============================================================================
# Fix API Endpoints
# =============================================================================


class IssueItem(BaseModel):
    """Issue data from HTML report (uses hash-based IDs)."""
    issue_id: str  # Hash-based ID from HTML report
    category: str
    severity: str
    title: str
    url: str
    element: Optional[str] = None  # Contains spelling correction info like '"ROT" → "ROI"'
    recommendation: Optional[str] = None  # Contains fix suggestion like "Change to: ROI"
    user_instructions: Optional[str] = None


class FixRequestFromReport(BaseModel):
    """Request to fix selected issues from HTML report."""
    scan_id: str
    issues: list[IssueItem]
    github_repo: str = "savaslabs/savaslabs.com"
    create_github_issues: bool = True


class FixBatchStatus(BaseModel):
    """Status of a fix batch."""
    batch_id: str
    total: int
    completed: int
    failed: int
    pending: int
    in_progress: int
    fixes: list[dict]


@app.post("/api/fix", response_model=FixResponse)
async def create_fixes(
    fix_request: FixRequestFromReport,
    background_tasks: BackgroundTasks,
    request: Request,
    auth: dict = Depends(verify_auth),
):
    """Create fixes for selected issues.

    Accepts issues selected from the HTML report with their hash-based IDs.
    Creates ProposedFix records and optionally GitHub issues.
    """
    # Verify scan exists
    scan = store.get_scan(fix_request.scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail=f"Scan not found: {fix_request.scan_id}")

    # Generate a batch ID for this fix request
    batch_id = str(uuid.uuid4())[:8]

    fixes_created = 0
    issue_data_map: dict[str, dict] = {}  # Map fix_id -> issue data

    # Process each selected issue
    for issue_item in fix_request.issues:
        # Create a temporary Issue object for classification
        from ..models import Issue, IssueCategory, Severity

        try:
            category = IssueCategory(issue_item.category)
        except ValueError:
            category = IssueCategory.SEO  # Fallback

        try:
            severity = Severity(issue_item.severity)
        except ValueError:
            severity = Severity.MEDIUM  # Fallback

        temp_issue = Issue(
            category=category,
            severity=severity,
            title=issue_item.title,
            description="",
            recommendation="",
            url=issue_item.url,
        )

        # Classify the issue
        fix_type = fix_classifier.classify(temp_issue)
        confidence = fix_classifier.get_confidence(temp_issue, fix_type)
        recommendation = fix_classifier.get_fix_description(temp_issue)

        # Generate a unique fix ID
        fix_id = f"{batch_id}-{fixes_created + 1}"

        # Parse original/corrected text from title and recommendation
        # Title format: "Spelling error: 'word'" or "Grammar issue: ..."
        # Recommendation format: "Change to: correction" or specific text
        import re
        original_value = None
        proposed_value = None

        # Extract from title: "Spelling error: 'word'" -> word
        title_match = re.search(r"error:\s*['\"]([^'\"]+)['\"]", issue_item.title, re.IGNORECASE)
        if title_match:
            original_value = title_match.group(1)

        # Extract from recommendation: "Change to: suggestion"
        rec_match = re.search(r"Change to:\s*(.+)", issue_item.recommendation or "", re.IGNORECASE)
        if rec_match:
            proposed_value = rec_match.group(1).strip()

        # Fallback: try broken link format in element: <a href="url">text</a>
        if not original_value and issue_item.element:
            link_match = re.search(r'(<a\s+href=["\'][^"\']+["\'][^>]*>[^<]+</a>)', issue_item.element, re.IGNORECASE)
            if link_match:
                full_link_html = link_match.group(1)
                # Extract just the text content
                text_match = re.search(r'>([^<]+)</a>', full_link_html, re.IGNORECASE)
                link_text = text_match.group(1) if text_match else ""
                # Original is the full <a> tag, proposed is just the text
                original_value = full_link_html
                proposed_value = link_text

        # Store issue data for background processing
        issue_data_map[fix_id] = {
            "category": issue_item.category,
            "severity": issue_item.severity,
            "title": issue_item.title,
            "description": "",
            "recommendation": recommendation,
            "url": issue_item.url,
            "element": issue_item.element,
        }

        # Create the proposed fix record
        proposed_fix = ProposedFix(
            id=fix_id,
            scan_id=fix_request.scan_id,
            issue_id=fixes_created,  # Sequential index since we don't have DB IDs
            fix_type=fix_type,
            status=FixStatus.PENDING,
            confidence=confidence,
            user_instructions=issue_item.user_instructions,
            original_value=original_value,
            proposed_value=proposed_value,
        )

        # Store the fix (batch_id is encoded in the fix id as prefix)
        store.create_fix(proposed_fix)
        fixes_created += 1

    # Trigger background task for GitHub issue creation if enabled and token available
    github_issues_created = 0
    if fix_request.create_github_issues and GITHUB_TOKEN:
        background_tasks.add_task(
            process_fix_batch,
            batch_id,
            issue_data_map,
            fix_request.github_repo,
        )
        message = f"Created {fixes_created} fix record(s). Processing in background."
    elif fix_request.create_github_issues and not GITHUB_TOKEN:
        message = f"Created {fixes_created} fix record(s). GitHub token not configured."
    else:
        message = f"Created {fixes_created} fix record(s)."

    return FixResponse(
        fix_batch_id=batch_id,
        fixes_created=fixes_created,
        github_issues_created=github_issues_created,
        message=message,
    )


async def process_fix_batch(
    batch_id: str,
    issue_data_map: dict[str, dict],
    github_repo: str,
):
    """Background task to process fixes in a batch.

    Creates GitHub issues and attempts auto-fixes where possible.
    """
    import traceback

    try:
        print(f"Starting batch {batch_id} processing with {len(issue_data_map)} issues")
        print(f"GitHub repo: {github_repo}")

        results = fix_orchestrator.process_batch(
            batch_id=batch_id,
            issue_data_map=issue_data_map,
            github_repo=github_repo,
        )

        # Log each result
        for r in results:
            status_icon = "✓" if r.success else "✗"
            print(f"  {status_icon} Fix {r.fix_id}: {r.status.value} - {r.message}")
            if r.github_issue_url:
                print(f"    GitHub: {r.github_issue_url}")
            if r.github_pr_url:
                print(f"    PR: {r.github_pr_url}")
            if r.drupal_revision_url:
                print(f"    Drupal: {r.drupal_revision_url}")

        # Log summary
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count
        print(f"Processed batch {batch_id}: {success_count} succeeded, {fail_count} failed")

    except Exception as e:
        print(f"Error processing batch {batch_id}: {e}")
        traceback.print_exc()


@app.get("/api/fix/{batch_id}/status", response_model=FixBatchStatus)
async def get_fix_batch_status(batch_id: str, request: Request, auth: dict = Depends(verify_auth)):
    """Get status of a fix batch."""
    fixes = store.get_fixes_by_batch(batch_id)
    if not fixes:
        raise HTTPException(status_code=404, detail=f"Fix batch not found: {batch_id}")

    # Count by status
    completed = sum(1 for f in fixes if f.status == FixStatus.APPLIED)
    failed = sum(1 for f in fixes if f.status == FixStatus.FAILED)
    pending = sum(1 for f in fixes if f.status == FixStatus.PENDING)
    in_progress = sum(1 for f in fixes if f.status == FixStatus.PROCESSING)

    return FixBatchStatus(
        batch_id=batch_id,
        total=len(fixes),
        completed=completed,
        failed=failed,
        pending=pending,
        in_progress=in_progress,
        fixes=[f.model_dump() for f in fixes],
    )


@app.get("/api/scan/{scan_id}/issues")
async def get_scan_issues(scan_id: str, request: Request, auth: dict = Depends(verify_auth)):
    """Get all issues for a scan with their database IDs.

    Returns issues grouped by category, with each issue including its database ID
    for use in fix requests.
    """
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    issues_by_category = store.get_issues_by_category(scan_id)
    return {
        "scan_id": scan_id,
        "issues_by_category": issues_by_category,
    }


@app.get("/api/scan/{scan_id}/fixes")
async def get_scan_fixes(scan_id: str, request: Request, auth: dict = Depends(verify_auth)):
    """Get all fixes associated with a scan."""
    fixes = store.get_fixes_for_scan(scan_id)
    return {
        "scan_id": scan_id,
        "fixes": [f.model_dump() for f in fixes],
    }


async def run_scan(scan_id: str, url: str, max_pages: int):
    """Background task to run a website scan."""
    import time
    start_time = time.time()

    # Send Slack notification for scan start
    notify_scan_started(url, max_pages, scan_id)

    try:
        store.update_scan_status(scan_id, "running")

        # Progress callback to update scan status
        def progress_callback(pages_done, pages_total, current_url):
            store.update_scan_status(
                scan_id,
                "running",
                pages_crawled=pages_done,
                pages_total=pages_total
            )

        # Crawl the site
        crawler = PlaywrightCrawler(url, max_pages=max_pages)
        crawl_results = await crawler.crawl(progress_callback=progress_callback)

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
                print(f"LinkAnalyzer failed: {e}")

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

        # Send Slack notification for scan completion
        duration_seconds = int(time.time() - start_time)
        notify_scan_completed(
            url=url,
            scan_id=scan_id,
            pages_crawled=len(pages),
            total_issues=summary.total_issues if summary else 0,
            overall_score=summary.overall_score if summary else 0,
            duration_seconds=duration_seconds,
        )

    except Exception as e:
        duration_seconds = int(time.time() - start_time)
        # Send Slack notification for scan failure
        notify_scan_failed(
            url=url,
            scan_id=scan_id,
            error=str(e),
            duration_seconds=duration_seconds,
        )
        store.update_scan_status(scan_id, "failed", error=str(e))
        raise


async def run_multi_url_scan(scan_id: str, urls: list[str]):
    """Background task to scan specific URLs without crawling.

    Fetches and analyzes each URL in the list directly.
    """
    import time
    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright

    start_time = time.time()
    primary_url = urls[0]

    # Send Slack notification for scan start
    notify_scan_started(primary_url, len(urls), scan_id)

    try:
        store.update_scan_status(scan_id, "running", pages_total=len(urls))

        pages = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            for i, url in enumerate(urls):
                try:
                    page = await context.new_page()
                    fetch_start = time.time()

                    response = await page.goto(url, wait_until="networkidle", timeout=30000)
                    status_code = response.status if response else 0
                    load_time_ms = (time.time() - fetch_start) * 1000

                    if status_code != 200:
                        pages.append(PageResult(
                            url=url,
                            status_code=status_code,
                            load_time_ms=load_time_ms,
                            crawled_at=datetime.utcnow(),
                        ))
                        await page.close()
                        continue

                    html = await page.content()
                    text = await page.inner_text("body")
                    soup = BeautifulSoup(html, "lxml")

                    # Run all analyzers
                    all_issues = []

                    for analyzer in analyzers:
                        try:
                            issues = analyzer.analyze(
                                url=url,
                                html=html,
                                text=text,
                                soup=soup,
                            )
                            all_issues.extend(issues)
                        except Exception as e:
                            print(f"Analyzer {analyzer.__class__.__name__} failed on {url}: {e}")

                    # Run async link checking
                    try:
                        link_issues = await link_analyzer.analyze_async(
                            url=url,
                            html=html,
                            text=text,
                            soup=soup,
                            base_url=primary_url,
                        )
                        all_issues.extend(link_issues)
                    except Exception as e:
                        print(f"LinkAnalyzer failed on {url}: {e}")

                    # Extract metadata
                    title_tag = soup.find("title")
                    title_text = title_tag.string.strip() if title_tag and title_tag.string else None

                    meta_desc = soup.find("meta", attrs={"name": "description"})
                    meta_desc_text = meta_desc.get("content", "").strip() if meta_desc else None

                    h1_tags = [h1.get_text(strip=True) for h1 in soup.find_all("h1")]

                    page_result = PageResult(
                        url=url,
                        status_code=status_code,
                        title=title_text,
                        meta_description=meta_desc_text,
                        h1_tags=h1_tags,
                        word_count=len(text.split()) if text else 0,
                        load_time_ms=load_time_ms,
                        issues=all_issues,
                        crawled_at=datetime.utcnow(),
                    )

                    pages.append(page_result)
                    store.save_page(scan_id, page_result)

                    await page.close()

                    # Update progress
                    store.update_scan_status(
                        scan_id, "running",
                        pages_crawled=i + 1,
                        pages_total=len(urls)
                    )

                except Exception as e:
                    print(f"Error fetching {url}: {e}")
                    pages.append(PageResult(
                        url=url,
                        status_code=0,
                        load_time_ms=0,
                        crawled_at=datetime.utcnow(),
                    ))

            await browser.close()

        # Create scan result and summary
        scan = ScanResult(
            id=scan_id,
            url=primary_url,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            status="completed",
            pages=pages,
        )

        summary = aggregator.aggregate(scan)
        store.update_scan_status(scan_id, "completed", summary=summary)

        # Send Slack notification for scan completion
        duration_seconds = int(time.time() - start_time)
        notify_scan_completed(
            url=primary_url,
            scan_id=scan_id,
            pages_crawled=len(pages),
            total_issues=summary.total_issues if summary else 0,
            overall_score=summary.overall_score if summary else 0,
            duration_seconds=duration_seconds,
        )

    except Exception as e:
        duration_seconds = int(time.time() - start_time)
        notify_scan_failed(
            url=primary_url,
            scan_id=scan_id,
            error=str(e),
            duration_seconds=duration_seconds,
        )
        store.update_scan_status(scan_id, "failed", error=str(e))
        raise


def run_server():
    """Run the API server."""
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)


if __name__ == "__main__":
    run_server()
