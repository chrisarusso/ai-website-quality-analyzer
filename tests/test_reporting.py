"""Tests for reporting module."""

import pytest
from datetime import datetime

from website_agent.models import (
    Issue,
    IssueCategory,
    PageResult,
    ScanResult,
    Severity,
)
from website_agent.reporting import ReportAggregator


class TestReportAggregator:
    """Tests for ReportAggregator."""

    def setup_method(self):
        self.aggregator = ReportAggregator()

    def create_test_scan(self, issues_per_page: int = 5, page_count: int = 3) -> ScanResult:
        """Create a test scan with sample issues."""
        pages = []
        for i in range(page_count):
            page_issues = []
            for j in range(issues_per_page):
                # Rotate through severities
                severities = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
                severity = severities[j % 4]

                # Rotate through categories
                categories = list(IssueCategory)
                category = categories[j % len(categories)]

                page_issues.append(Issue(
                    category=category,
                    severity=severity,
                    title=f"Test issue {j}",
                    description="Test description",
                    recommendation="Fix it",
                    url=f"https://example.com/page{i}",
                ))

            pages.append(PageResult(
                url=f"https://example.com/page{i}",
                status_code=200,
                title=f"Page {i}",
                word_count=500,
                issues=page_issues,
            ))

        return ScanResult(
            id="test123",
            url="https://example.com",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            status="completed",
            pages=pages,
        )

    def test_aggregate_counts(self):
        """Test that aggregation counts issues correctly."""
        scan = self.create_test_scan(issues_per_page=4, page_count=2)
        summary = self.aggregator.aggregate(scan)

        assert summary.total_pages == 2
        assert summary.pages_analyzed == 2
        assert summary.total_issues == 8  # 4 issues * 2 pages

    def test_aggregate_severity_counts(self):
        """Test severity counting."""
        scan = self.create_test_scan(issues_per_page=4, page_count=1)
        summary = self.aggregator.aggregate(scan)

        # With 4 issues rotating through severities: 1 of each
        assert summary.critical_issues == 1
        assert summary.high_issues == 1
        assert summary.medium_issues == 1
        assert summary.low_issues == 1

    def test_overall_score_calculation(self):
        """Test overall score is calculated."""
        scan = self.create_test_scan()
        summary = self.aggregator.aggregate(scan)

        assert 0 <= summary.overall_score <= 100

    def test_category_scores(self):
        """Test category scores are generated."""
        scan = self.create_test_scan()
        summary = self.aggregator.aggregate(scan)

        assert len(summary.category_scores) > 0
        for cat_score in summary.category_scores:
            assert 0 <= cat_score.score <= 100

    def test_top_issues_prioritization(self):
        """Test that top issues are sorted by severity."""
        scan = self.create_test_scan(issues_per_page=10)
        summary = self.aggregator.aggregate(scan)

        if len(summary.top_issues) > 1:
            # Critical should come before High, etc.
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            for i in range(len(summary.top_issues) - 1):
                current = severity_order.get(summary.top_issues[i].severity, 4)
                next_issue = severity_order.get(summary.top_issues[i + 1].severity, 4)
                assert current <= next_issue

    def test_text_report_generation(self):
        """Test text report is generated."""
        scan = self.create_test_scan()
        summary = self.aggregator.aggregate(scan)
        report = self.aggregator.generate_text_report(scan, summary)

        assert "WEBSITE QUALITY REPORT" in report
        assert "example.com" in report
        assert "Overall Score" in report

    def test_html_report_generation(self):
        """Test HTML report is generated."""
        scan = self.create_test_scan()
        summary = self.aggregator.aggregate(scan)
        html = self.aggregator.generate_html_report(scan, summary)

        assert "<!DOCTYPE html>" in html
        assert "example.com" in html
        assert str(summary.overall_score) in html

    def test_empty_scan(self):
        """Test handling of scan with no pages."""
        scan = ScanResult(
            id="empty",
            url="https://example.com",
            started_at=datetime.utcnow(),
            status="completed",
            pages=[],
        )
        summary = self.aggregator.aggregate(scan)

        assert summary.total_pages == 0
        assert summary.total_issues == 0
        assert summary.overall_score == 100  # Perfect score with no issues

    def test_scan_with_failed_pages(self):
        """Test handling of pages with non-200 status."""
        pages = [
            PageResult(url="https://example.com/ok", status_code=200, issues=[]),
            PageResult(url="https://example.com/404", status_code=404, issues=[]),
            PageResult(url="https://example.com/500", status_code=500, issues=[]),
        ]
        scan = ScanResult(
            id="mixed",
            url="https://example.com",
            started_at=datetime.utcnow(),
            status="completed",
            pages=pages,
        )
        summary = self.aggregator.aggregate(scan)

        assert summary.total_pages == 3
        assert summary.pages_analyzed == 1  # Only the 200 page
