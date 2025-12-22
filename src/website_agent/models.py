"""Pydantic models for Website Quality Agent.

Defines data structures for pages, issues, reports, and scan results.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class Severity(str, Enum):
    """Issue severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueCategory(str, Enum):
    """Categories of quality issues."""
    SEO = "seo"
    SPELLING = "spelling"
    GRAMMAR = "grammar"
    FORMATTING = "formatting"
    ACCESSIBILITY = "accessibility"
    LINKS = "links"
    COMPLIANCE = "compliance"
    PERFORMANCE = "performance"
    MOBILE = "mobile"
    SECURITY = "security"


class Issue(BaseModel):
    """A single quality issue found on a page."""
    category: IssueCategory
    severity: Severity
    title: str = Field(..., description="Short description of the issue")
    description: str = Field(..., description="Detailed explanation")
    recommendation: str = Field(..., description="How to fix the issue")
    url: str = Field(..., description="URL where issue was found")
    element: Optional[str] = Field(None, description="HTML element or selector")
    context: Optional[str] = Field(None, description="Surrounding content for context")
    line_number: Optional[int] = Field(None, description="Line number if applicable")

    class Config:
        use_enum_values = True


class PageResult(BaseModel):
    """Analysis results for a single page."""
    url: str
    status_code: int
    title: Optional[str] = None
    meta_description: Optional[str] = None
    h1_tags: list[str] = Field(default_factory=list)
    word_count: int = 0
    load_time_ms: float = 0.0
    issues: list[Issue] = Field(default_factory=list)
    crawled_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.HIGH)


class CategoryScore(BaseModel):
    """Score for a single category."""
    category: IssueCategory
    score: float = Field(..., ge=0, le=100, description="Score from 0-100")
    issue_count: int
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    class Config:
        use_enum_values = True


class ScanSummary(BaseModel):
    """Summary statistics for a complete site scan."""
    total_pages: int
    pages_analyzed: int
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    overall_score: float = Field(..., ge=0, le=100)
    category_scores: list[CategoryScore] = Field(default_factory=list)
    top_issues: list[Issue] = Field(default_factory=list, description="Top 10 priority issues")


class CMSInfo(BaseModel):
    """Detected CMS information."""
    name: Optional[str] = None
    version: Optional[str] = None
    detected_plugins: list[str] = Field(default_factory=list)
    security_issues: list[str] = Field(default_factory=list)


class ScanResult(BaseModel):
    """Complete scan result for a website."""
    id: str = Field(..., description="Unique scan ID")
    url: str = Field(..., description="Base URL that was scanned")
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str = Field(default="pending", description="pending, running, completed, failed")
    pages: list[PageResult] = Field(default_factory=list)
    summary: Optional[ScanSummary] = None
    cms_info: Optional[CMSInfo] = None
    error: Optional[str] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class ScanRequest(BaseModel):
    """Request to start a new scan."""
    url: HttpUrl
    max_pages: int = Field(default=50, ge=1, le=500)
    include_external_links: bool = False
    categories: list[IssueCategory] = Field(
        default_factory=lambda: list(IssueCategory),
        description="Categories to check"
    )


class ScanStatus(BaseModel):
    """Status of an ongoing or completed scan."""
    id: str
    url: str
    status: str
    pages_crawled: int = 0
    pages_total: int = 0
    issues_found: int = 0
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
