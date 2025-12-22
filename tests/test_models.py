"""Tests for Pydantic models."""

import pytest
from datetime import datetime

from website_agent.models import (
    Issue,
    IssueCategory,
    PageResult,
    ScanResult,
    ScanSummary,
    CategoryScore,
    Severity,
)


class TestIssue:
    """Tests for Issue model."""

    def test_create_issue(self):
        """Test creating a basic issue."""
        issue = Issue(
            category=IssueCategory.SEO,
            severity=Severity.HIGH,
            title="Missing title tag",
            description="The page does not have a title tag.",
            recommendation="Add a title tag.",
            url="https://example.com/page",
        )
        assert issue.category == "seo"
        assert issue.severity == "high"
        assert issue.title == "Missing title tag"

    def test_issue_with_optional_fields(self):
        """Test issue with all optional fields."""
        issue = Issue(
            category=IssueCategory.ACCESSIBILITY,
            severity=Severity.MEDIUM,
            title="Image missing alt",
            description="Image has no alt text.",
            recommendation="Add alt text.",
            url="https://example.com/",
            element="<img src='test.jpg'>",
            context="Header section",
            line_number=42,
        )
        assert issue.element == "<img src='test.jpg'>"
        assert issue.context == "Header section"
        assert issue.line_number == 42


class TestPageResult:
    """Tests for PageResult model."""

    def test_create_page_result(self):
        """Test creating a page result."""
        page = PageResult(
            url="https://example.com/",
            status_code=200,
            title="Example",
            word_count=500,
            load_time_ms=1200.5,
        )
        assert page.url == "https://example.com/"
        assert page.status_code == 200
        assert page.issue_count == 0

    def test_page_result_with_issues(self):
        """Test page result with issues."""
        issues = [
            Issue(
                category=IssueCategory.SEO,
                severity=Severity.CRITICAL,
                title="Test issue",
                description="Test",
                recommendation="Fix it",
                url="https://example.com/",
            ),
            Issue(
                category=IssueCategory.SEO,
                severity=Severity.HIGH,
                title="Another issue",
                description="Test",
                recommendation="Fix it",
                url="https://example.com/",
            ),
        ]
        page = PageResult(
            url="https://example.com/",
            status_code=200,
            issues=issues,
        )
        assert page.issue_count == 2
        assert page.critical_count == 1
        assert page.high_count == 1


class TestScanSummary:
    """Tests for ScanSummary model."""

    def test_create_summary(self):
        """Test creating a scan summary."""
        summary = ScanSummary(
            total_pages=10,
            pages_analyzed=10,
            total_issues=25,
            critical_issues=2,
            high_issues=5,
            medium_issues=10,
            low_issues=8,
            overall_score=75.5,
        )
        assert summary.total_pages == 10
        assert summary.overall_score == 75.5


class TestCategoryScore:
    """Tests for CategoryScore model."""

    def test_create_category_score(self):
        """Test creating a category score."""
        score = CategoryScore(
            category=IssueCategory.SEO,
            score=85.0,
            issue_count=5,
            critical_count=0,
            high_count=1,
            medium_count=2,
            low_count=2,
        )
        assert score.category == "seo"
        assert score.score == 85.0
        assert score.issue_count == 5


class TestSeverity:
    """Tests for Severity enum."""

    def test_severity_values(self):
        """Test severity enum values."""
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.LOW.value == "low"


class TestIssueCategory:
    """Tests for IssueCategory enum."""

    def test_category_values(self):
        """Test all category values exist."""
        categories = [
            "seo", "spelling", "grammar", "formatting",
            "accessibility", "links", "compliance",
            "performance", "mobile", "security",
        ]
        for cat in categories:
            assert cat in [c.value for c in IssueCategory]
