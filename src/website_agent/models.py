from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


class Severity(str, Enum):
    critical = "Critical"
    high = "High"
    medium = "Medium"
    low = "Low"


class Issue(BaseModel):
    category: str
    severity: Severity
    message: str
    location: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class PageResult(BaseModel):
    url: HttpUrl
    status_code: int
    content: Optional[str] = None
    fetched_at: datetime


class ScanSummary(BaseModel):
    scan_id: int
    root_url: HttpUrl
    created_at: datetime
    page_count: int
    issue_count: int
    issues_by_severity: Dict[Severity, int]
    issues_by_category: Dict[str, int]
    top_messages: List[str] = []

