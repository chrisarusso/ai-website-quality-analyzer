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
from ..models import (
    Issue,
    PageResult,
    ProposedFix,
    ScanResult,
    ScanStatus,
    ScanSummary,
    FixStatus,
    FixType,
)


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

                -- Proposed fixes table for auto-fix feature
                CREATE TABLE IF NOT EXISTS proposed_fixes (
                    id TEXT PRIMARY KEY,
                    scan_id TEXT NOT NULL,
                    issue_id INTEGER NOT NULL,
                    fix_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    target_type TEXT,
                    target_id TEXT,
                    target_field TEXT,
                    original_value TEXT,
                    proposed_value TEXT,
                    user_instructions TEXT,
                    confidence REAL DEFAULT 0.0,
                    ai_generated INTEGER DEFAULT 1,
                    github_issue_url TEXT,
                    github_issue_number INTEGER,
                    github_pr_url TEXT,
                    drupal_revision_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    error_message TEXT,
                    FOREIGN KEY (scan_id) REFERENCES scans(id),
                    FOREIGN KEY (issue_id) REFERENCES issues(id)
                );

                CREATE INDEX IF NOT EXISTS idx_fixes_scan_id ON proposed_fixes(scan_id);
                CREATE INDEX IF NOT EXISTS idx_fixes_status ON proposed_fixes(status);
                CREATE INDEX IF NOT EXISTS idx_fixes_issue_id ON proposed_fixes(issue_id);
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
            conn.execute("DELETE FROM proposed_fixes WHERE scan_id = ?", (scan_id,))
            conn.execute("DELETE FROM issues WHERE scan_id = ?", (scan_id,))
            conn.execute("DELETE FROM pages WHERE scan_id = ?", (scan_id,))
            conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
            conn.commit()
        finally:
            conn.close()

    # =========================================================================
    # Fix-related methods
    # =========================================================================

    def get_issue_by_id(self, issue_id: int) -> Optional[Issue]:
        """Get a single issue by its database ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM issues WHERE id = ?", (issue_id,)
            ).fetchone()

            if not row:
                return None

            return Issue(
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
        finally:
            conn.close()

    def get_issues_with_ids(self, scan_id: str) -> list[dict]:
        """Get issues with their database IDs for the fix UI."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT id, scan_id, page_url, category, severity, title,
                          description, recommendation, element, context, line_number
                   FROM issues WHERE scan_id = ? ORDER BY severity, category""",
                (scan_id,),
            ).fetchall()

            return [
                {
                    "id": row["id"],
                    "scan_id": row["scan_id"],
                    "url": row["page_url"],
                    "category": row["category"],
                    "severity": row["severity"],
                    "title": row["title"],
                    "description": row["description"] or "",
                    "recommendation": row["recommendation"] or "",
                    "element": row["element"],
                    "context": row["context"],
                    "line_number": row["line_number"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def create_fix(self, fix: ProposedFix) -> ProposedFix:
        """Create a new proposed fix record."""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO proposed_fixes
                   (id, scan_id, issue_id, fix_type, status, target_type, target_id,
                    target_field, original_value, proposed_value, user_instructions,
                    confidence, ai_generated, github_issue_url, github_issue_number,
                    github_pr_url, drupal_revision_url, created_at, updated_at,
                    reviewed_at, reviewed_by, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fix.id,
                    fix.scan_id,
                    fix.issue_id,
                    fix.fix_type,
                    fix.status,
                    fix.target_type,
                    fix.target_id,
                    fix.target_field,
                    fix.original_value,
                    fix.proposed_value,
                    fix.user_instructions,
                    fix.confidence,
                    1 if fix.ai_generated else 0,
                    fix.github_issue_url,
                    fix.github_issue_number,
                    fix.github_pr_url,
                    fix.drupal_revision_url,
                    fix.created_at.isoformat(),
                    fix.updated_at.isoformat() if fix.updated_at else None,
                    fix.reviewed_at.isoformat() if fix.reviewed_at else None,
                    fix.reviewed_by,
                    fix.error_message,
                ),
            )
            conn.commit()
            return fix
        finally:
            conn.close()

    def update_fix_status(
        self,
        fix_id: str,
        status: Optional[FixStatus] = None,
        github_issue_url: Optional[str] = None,
        github_issue_number: Optional[int] = None,
        github_pr_url: Optional[str] = None,
        drupal_revision_url: Optional[str] = None,
        proposed_value: Optional[str] = None,
        original_value: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        """Update a fix record."""
        conn = self._get_conn()
        try:
            updates = ["updated_at = ?"]
            params = [datetime.utcnow().isoformat()]

            if status is not None:
                updates.append("status = ?")
                params.append(status.value if isinstance(status, FixStatus) else status)

            if github_issue_url is not None:
                updates.append("github_issue_url = ?")
                params.append(github_issue_url)

            if github_issue_number is not None:
                updates.append("github_issue_number = ?")
                params.append(github_issue_number)

            if github_pr_url is not None:
                updates.append("github_pr_url = ?")
                params.append(github_pr_url)

            if drupal_revision_url is not None:
                updates.append("drupal_revision_url = ?")
                params.append(drupal_revision_url)

            if proposed_value is not None:
                updates.append("proposed_value = ?")
                params.append(proposed_value)

            if original_value is not None:
                updates.append("original_value = ?")
                params.append(original_value)

            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)

            params.append(fix_id)
            conn.execute(
                f"UPDATE proposed_fixes SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

    def get_fix(self, fix_id: str) -> Optional[ProposedFix]:
        """Get a fix by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM proposed_fixes WHERE id = ?", (fix_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_fix(row)
        finally:
            conn.close()

    def get_fixes_for_scan(self, scan_id: str) -> list[ProposedFix]:
        """Get all fixes for a scan."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM proposed_fixes WHERE scan_id = ? ORDER BY created_at",
                (scan_id,),
            ).fetchall()

            return [self._row_to_fix(row) for row in rows]
        finally:
            conn.close()

    def get_fixes_by_batch(self, batch_id: str) -> list[ProposedFix]:
        """Get all fixes in a batch (fixes whose ID starts with the batch ID)."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM proposed_fixes WHERE id LIKE ? ORDER BY created_at",
                (f"{batch_id}-%",),
            ).fetchall()

            return [self._row_to_fix(row) for row in rows]
        finally:
            conn.close()

    def get_pending_fixes(self) -> list[ProposedFix]:
        """Get all pending fixes across all scans."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM proposed_fixes WHERE status IN ('pending', 'processing') ORDER BY created_at",
            ).fetchall()

            return [self._row_to_fix(row) for row in rows]
        finally:
            conn.close()

    def _row_to_fix(self, row: sqlite3.Row) -> ProposedFix:
        """Convert a database row to a ProposedFix object."""
        return ProposedFix(
            id=row["id"],
            scan_id=row["scan_id"],
            issue_id=row["issue_id"],
            fix_type=FixType(row["fix_type"]),
            status=FixStatus(row["status"]),
            target_type=row["target_type"],
            target_id=row["target_id"],
            target_field=row["target_field"],
            original_value=row["original_value"],
            proposed_value=row["proposed_value"],
            user_instructions=row["user_instructions"],
            confidence=row["confidence"],
            ai_generated=bool(row["ai_generated"]),
            github_issue_url=row["github_issue_url"],
            github_issue_number=row["github_issue_number"],
            github_pr_url=row["github_pr_url"],
            drupal_revision_url=row["drupal_revision_url"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            reviewed_at=datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None,
            reviewed_by=row["reviewed_by"],
            error_message=row["error_message"],
        )

    def delete_fixes_for_scan(self, scan_id: str):
        """Delete all fixes for a scan."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM proposed_fixes WHERE scan_id = ?", (scan_id,))
            conn.commit()
        finally:
            conn.close()
