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


# =============================================================================
# Fix-related models for the auto-fix feature
# =============================================================================


class FixType(str, Enum):
    """Classification of how an issue can be fixed."""
    CODE_FIX = "code_fix"        # Fix via Git PR (templates, config)
    CONTENT_FIX = "content_fix"  # Fix via CMS (Drupal content/media)
    MANUAL_ONLY = "manual_only"  # Requires human judgment
    NOT_FIXABLE = "not_fixable"  # Detection-only (3rd party, external)


class FixStatus(str, Enum):
    """Status of a proposed fix."""
    PENDING = "pending"              # Created, awaiting processing
    PROCESSING = "processing"        # Agent is working on it
    PR_CREATED = "pr_created"        # GitHub PR created, awaiting review
    DRAFT_CREATED = "draft_created"  # Drupal draft revision created
    APPROVED = "approved"            # Human approved
    REJECTED = "rejected"            # Human rejected
    APPLIED = "applied"              # Fix successfully applied
    FAILED = "failed"                # Fix attempt failed


class ProposedFix(BaseModel):
    """A proposed fix for an issue."""
    id: str = Field(..., description="Unique fix ID")
    scan_id: str = Field(..., description="Reference to the scan")
    issue_id: int = Field(..., description="Reference to issues.id from SQLite")

    # Classification
    fix_type: FixType
    status: FixStatus = FixStatus.PENDING

    # Target information
    target_type: Optional[str] = Field(
        None, description="drupal_media, drupal_node, or git_file"
    )
    target_id: Optional[str] = Field(
        None, description="UUID, node ID, or file path"
    )
    target_field: Optional[str] = Field(
        None, description="For Drupal: which field to update"
    )

    # The fix
    original_value: Optional[str] = None
    proposed_value: Optional[str] = None

    # User context
    user_instructions: Optional[str] = Field(
        None, description="User-provided context or instructions"
    )

    # Metadata
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    ai_generated: bool = True

    # Tracking
    github_issue_url: Optional[str] = None
    github_issue_number: Optional[int] = None
    github_pr_url: Optional[str] = None
    drupal_revision_url: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None

    # Error tracking
    error_message: Optional[str] = None

    class Config:
        use_enum_values = True


class FixRequestItem(BaseModel):
    """Single issue to fix with optional user context."""
    issue_id: int
    user_instructions: Optional[str] = None


class FixRequest(BaseModel):
    """Request to fix selected issues."""
    scan_id: str
    issues: list[FixRequestItem]
    github_repo: str = "savaslabs/savaslabs.com"
    create_github_issues: bool = True


class FixResponse(BaseModel):
    """Response after initiating fix process."""
    fix_batch_id: str
    fixes_created: int
    github_issues_created: int
    message: str
