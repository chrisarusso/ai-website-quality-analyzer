"""SQLite storage for scan results and crawled content.

Provides persistent storage for:
- Scan metadata and status
- Page results and issues
- Crawled HTML content (optional)
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import DATABASE_PATH, ensure_data_dir
from ..models import Issue, PageResult, ScanResult, ScanStatus, ScanSummary


class SQLiteStore:
    """SQLite-based storage for scan results."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize storage.

        Args:
            db_path: Path to SQLite database file. Defaults to config value.
        """
        self.db_path = db_path or DATABASE_PATH
        ensure_data_dir()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scans (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    summary_json TEXT,
                    cms_info_json TEXT,
                    error TEXT,
                    pages_crawled INTEGER DEFAULT 0,
                    pages_total INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status_code INTEGER,
                    title TEXT,
                    meta_description TEXT,
                    h1_tags_json TEXT,
                    word_count INTEGER DEFAULT 0,
                    load_time_ms REAL DEFAULT 0,
                    crawled_at TEXT,
                    html TEXT,
                    FOREIGN KEY (scan_id) REFERENCES scans(id)
                );

                CREATE TABLE IF NOT EXISTS issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id TEXT NOT NULL,
                    page_url TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    recommendation TEXT,
                    element TEXT,
                    context TEXT,
                    line_number INTEGER,
                    FOREIGN KEY (scan_id) REFERENCES scans(id)
                );

                CREATE INDEX IF NOT EXISTS idx_pages_scan_id ON pages(scan_id);
                CREATE INDEX IF NOT EXISTS idx_issues_scan_id ON issues(scan_id);
                CREATE INDEX IF NOT EXISTS idx_issues_category ON issues(category);
                CREATE INDEX IF NOT EXISTS idx_issues_severity ON issues(severity);
            """)
            conn.commit()
        finally:
            conn.close()

    def create_scan(self, scan_id: str, url: str) -> ScanStatus:
        """Create a new scan record."""
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()
        try:
            conn.execute(
                "INSERT INTO scans (id, url, status, started_at) VALUES (?, ?, ?, ?)",
                (scan_id, url, "pending", now),
            )
            conn.commit()
            return ScanStatus(
                id=scan_id,
                url=url,
                status="pending",
                started_at=datetime.fromisoformat(now),
            )
        finally:
            conn.close()

    def update_scan_status(
        self,
        scan_id: str,
        status: str,
        error: Optional[str] = None,
        summary: Optional[ScanSummary] = None,
        pages_crawled: Optional[int] = None,
        pages_total: Optional[int] = None,
    ):
        """Update scan status."""
        conn = self._get_conn()
        try:
            updates = ["status = ?"]
            params = [status]

            if status in ("completed", "failed"):
                updates.append("completed_at = ?")
                params.append(datetime.utcnow().isoformat())

            if error:
                updates.append("error = ?")
                params.append(error)

            if summary:
                updates.append("summary_json = ?")
                params.append(summary.model_dump_json())

            if pages_crawled is not None:
                updates.append("pages_crawled = ?")
                params.append(pages_crawled)

            if pages_total is not None:
                updates.append("pages_total = ?")
                params.append(pages_total)

            params.append(scan_id)
            conn.execute(
                f"UPDATE scans SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

    def save_page(self, scan_id: str, page: PageResult, save_html: bool = False):
        """Save a page result."""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO pages
                   (scan_id, url, status_code, title, meta_description,
                    h1_tags_json, word_count, load_time_ms, crawled_at, html)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    scan_id,
                    page.url,
                    page.status_code,
                    page.title,
                    page.meta_description,
                    json.dumps(page.h1_tags),
                    page.word_count,
                    page.load_time_ms,
                    page.crawled_at.isoformat(),
                    None,  # Don't save HTML by default to save space
                ),
            )

            # Save issues
            for issue in page.issues:
                conn.execute(
                    """INSERT INTO issues
                       (scan_id, page_url, category, severity, title,
                        description, recommendation, element, context, line_number)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        scan_id,
                        issue.url,
                        issue.category,
                        issue.severity,
                        issue.title,
                        issue.description,
                        issue.recommendation,
                        issue.element,
                        issue.context,
                        issue.line_number,
                    ),
                )

            conn.commit()
        finally:
            conn.close()

    def get_scan(self, scan_id: str) -> Optional[ScanResult]:
        """Get a scan by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM scans WHERE id = ?", (scan_id,)
            ).fetchone()

            if not row:
                return None

            # Get pages
            pages = []
            page_rows = conn.execute(
                "SELECT * FROM pages WHERE scan_id = ?", (scan_id,)
            ).fetchall()

            for page_row in page_rows:
                # Get issues for this page
                issue_rows = conn.execute(
                    "SELECT * FROM issues WHERE scan_id = ? AND page_url = ?",
                    (scan_id, page_row["url"]),
                ).fetchall()

                issues = [
                    Issue(
                        category=ir["category"],
                        severity=ir["severity"],
                        title=ir["title"],
                        description=ir["description"] or "",
                        recommendation=ir["recommendation"] or "",
                        url=ir["page_url"],
                        element=ir["element"],
                        context=ir["context"],
                        line_number=ir["line_number"],
                    )
                    for ir in issue_rows
                ]

                pages.append(PageResult(
                    url=page_row["url"],
                    status_code=page_row["status_code"],
                    title=page_row["title"],
                    meta_description=page_row["meta_description"],
                    h1_tags=json.loads(page_row["h1_tags_json"]) if page_row["h1_tags_json"] else [],
                    word_count=page_row["word_count"],
                    load_time_ms=page_row["load_time_ms"],
                    issues=issues,
                    crawled_at=datetime.fromisoformat(page_row["crawled_at"]),
                ))

            summary = None
            if row["summary_json"]:
                summary = ScanSummary.model_validate_json(row["summary_json"])

            return ScanResult(
                id=row["id"],
                url=row["url"],
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                status=row["status"],
                pages=pages,
                summary=summary,
                error=row["error"],
            )
        finally:
            conn.close()

    def get_scan_status(self, scan_id: str) -> Optional[ScanStatus]:
        """Get scan status."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id, url, status, started_at, completed_at, error, pages_crawled, pages_total FROM scans WHERE id = ?",
                (scan_id,),
            ).fetchone()

            if not row:
                return None

            # Count issues from database
            issues_count = conn.execute(
                "SELECT COUNT(*) FROM issues WHERE scan_id = ?", (scan_id,)
            ).fetchone()[0]

            return ScanStatus(
                id=row["id"],
                url=row["url"],
                status=row["status"],
                pages_crawled=row["pages_crawled"] or 0,
                pages_total=row["pages_total"] or 0,
                issues_found=issues_count,
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                error=row["error"],
            )
        finally:
            conn.close()

    def list_scans(self, limit: int = 20) -> list[ScanStatus]:
        """List recent scans."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT id, url, status, started_at, completed_at, error
                   FROM scans ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()

            return [
                ScanStatus(
                    id=row["id"],
                    url=row["url"],
                    status=row["status"],
                    started_at=datetime.fromisoformat(row["started_at"]),
                    completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                    error=row["error"],
                )
                for row in rows
            ]
        finally:
            conn.close()

    def get_issues_by_category(self, scan_id: str) -> dict[str, list[Issue]]:
        """Get issues grouped by category."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM issues WHERE scan_id = ? ORDER BY category, severity",
                (scan_id,),
            ).fetchall()

            result: dict[str, list[Issue]] = {}
            for row in rows:
                issue = Issue(
                    category=row["category"],
                    severity=row["severity"],
                    title=row["title"],
                    description=row["description"] or "",
                    recommendation=row["recommendation"] or "",
                    url=row["page_url"],
                    element=row["element"],
                    context=row["context"],
                    line_number=row["line_number"],
                )
                if row["category"] not in result:
                    result[row["category"]] = []
                result[row["category"]].append(issue)

            return result
        finally:
            conn.close()

    def delete_scan(self, scan_id: str):
        """Delete a scan and all related data."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM issues WHERE scan_id = ?", (scan_id,))
            conn.execute("DELETE FROM pages WHERE scan_id = ?", (scan_id,))
            conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
            conn.commit()
        finally:
            conn.close()
