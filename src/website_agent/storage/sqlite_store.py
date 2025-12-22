import json
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

from website_agent.models import Issue, PageResult


class SQLiteStore:
    def __init__(self, path: str = "data/agent.db"):
        self.path = Path(path)
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    status_code INTEGER,
                    content TEXT,
                    fetched_at TEXT,
                    FOREIGN KEY (scan_id) REFERENCES scans(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id INTEGER NOT NULL,
                    page_id INTEGER,
                    category TEXT,
                    severity TEXT,
                    message TEXT,
                    location TEXT,
                    meta TEXT,
                    FOREIGN KEY (scan_id) REFERENCES scans(id),
                    FOREIGN KEY (page_id) REFERENCES pages(id)
                )
                """
            )
            conn.commit()

    def create_scan(self, root_url: str, created_at: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO scans (root_url, created_at) VALUES (?, ?)",
                (root_url, created_at),
            )
            conn.commit()
            return cur.lastrowid

    def save_pages(self, scan_id: int, pages: Iterable[PageResult]) -> List[int]:
        ids: List[int] = []
        with self._connect() as conn:
            for page in pages:
                cur = conn.execute(
                    "INSERT INTO pages (scan_id, url, status_code, content, fetched_at) VALUES (?, ?, ?, ?, ?)",
                    (scan_id, str(page.url), page.status_code, page.content, page.fetched_at.isoformat()),
                )
                ids.append(cur.lastrowid)
            conn.commit()
        return ids

    def save_issues(self, scan_id: int, page_id_lookup: dict[str, int], issues: Iterable[Issue]):
        with self._connect() as conn:
            for issue in issues:
                page_id = page_id_lookup.get(issue.location or "", None)
                conn.execute(
                    "INSERT INTO issues (scan_id, page_id, category, severity, message, location, meta) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        scan_id,
                        page_id,
                        issue.category,
                        issue.severity.value,
                        issue.message,
                        issue.location,
                        json.dumps(issue.meta or {}),
                    ),
                )
            conn.commit()

    def list_scans(self):
        with self._connect() as conn:
            cur = conn.execute("SELECT id, root_url, created_at FROM scans ORDER BY id DESC")
            return cur.fetchall()

    def get_scan(self, scan_id: int):
        with self._connect() as conn:
            cur = conn.execute("SELECT id, root_url, created_at FROM scans WHERE id = ?", (scan_id,))
            return cur.fetchone()

    def get_pages(self, scan_id: int):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id, url, status_code, fetched_at FROM pages WHERE scan_id = ? ORDER BY id",
                (scan_id,),
            )
            return cur.fetchall()

    def get_issues(self, scan_id: int):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT category, severity, message, location, meta FROM issues WHERE scan_id = ? ORDER BY id",
                (scan_id,),
            )
            return cur.fetchall()

