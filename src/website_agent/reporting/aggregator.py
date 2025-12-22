"""Report aggregator for combining and scoring scan results.

Combines issues from all pages, calculates scores, and generates summaries.
"""

from collections import defaultdict
from typing import Optional

from ..config import SEVERITY_WEIGHTS
from ..models import (
    CategoryScore,
    Issue,
    IssueCategory,
    PageResult,
    ScanResult,
    ScanSummary,
    Severity,
)


class ReportAggregator:
    """Aggregates scan results into summary reports."""

    def __init__(self, max_score: float = 100.0):
        """Initialize aggregator.

        Args:
            max_score: Maximum possible score (default 100)
        """
        self.max_score = max_score

    def aggregate(self, scan: ScanResult) -> ScanSummary:
        """Aggregate all page results into a summary.

        Args:
            scan: Complete scan result with pages

        Returns:
            ScanSummary with scores and statistics
        """
        all_issues = []
        for page in scan.pages:
            all_issues.extend(page.issues)

        # Count by severity
        severity_counts = self._count_by_severity(all_issues)

        # Calculate category scores
        category_scores = self._calculate_category_scores(all_issues)

        # Calculate overall score
        overall_score = self._calculate_overall_score(all_issues, len(scan.pages))

        # Get top priority issues
        top_issues = self._get_top_issues(all_issues, limit=10)

        return ScanSummary(
            total_pages=len(scan.pages),
            pages_analyzed=len([p for p in scan.pages if p.status_code == 200]),
            total_issues=len(all_issues),
            critical_issues=severity_counts.get(Severity.CRITICAL, 0),
            high_issues=severity_counts.get(Severity.HIGH, 0),
            medium_issues=severity_counts.get(Severity.MEDIUM, 0),
            low_issues=severity_counts.get(Severity.LOW, 0),
            overall_score=overall_score,
            category_scores=category_scores,
            top_issues=top_issues,
        )

    def _count_by_severity(self, issues: list[Issue]) -> dict[Severity, int]:
        """Count issues by severity."""
        counts: dict[Severity, int] = defaultdict(int)
        for issue in issues:
            counts[Severity(issue.severity)] += 1
        return dict(counts)

    def _calculate_category_scores(self, issues: list[Issue]) -> list[CategoryScore]:
        """Calculate scores for each category."""
        category_issues: dict[str, list[Issue]] = defaultdict(list)
        for issue in issues:
            category_issues[issue.category].append(issue)

        scores = []
        for category in IssueCategory:
            cat_issues = category_issues.get(category.value, [])

            # Count by severity
            critical = sum(1 for i in cat_issues if i.severity == Severity.CRITICAL)
            high = sum(1 for i in cat_issues if i.severity == Severity.HIGH)
            medium = sum(1 for i in cat_issues if i.severity == Severity.MEDIUM)
            low = sum(1 for i in cat_issues if i.severity == Severity.LOW)

            # Calculate score (100 minus weighted penalties)
            penalty = (
                critical * SEVERITY_WEIGHTS["critical"]
                + high * SEVERITY_WEIGHTS["high"]
                + medium * SEVERITY_WEIGHTS["medium"]
                + low * SEVERITY_WEIGHTS["low"]
            )
            score = max(0, self.max_score - penalty)

            scores.append(CategoryScore(
                category=category,
                score=round(score, 1),
                issue_count=len(cat_issues),
                critical_count=critical,
                high_count=high,
                medium_count=medium,
                low_count=low,
            ))

        return scores

    def _calculate_overall_score(self, issues: list[Issue], page_count: int) -> float:
        """Calculate overall site score.

        Score starts at 100 and decreases based on issues found.
        Normalized by page count to avoid penalizing larger sites.
        """
        if page_count == 0:
            return self.max_score

        total_penalty = 0
        for issue in issues:
            weight = SEVERITY_WEIGHTS.get(issue.severity, 1)
            total_penalty += weight

        # Normalize by page count (average penalty per page)
        avg_penalty = total_penalty / page_count

        # Cap penalty at 100
        score = max(0, self.max_score - min(avg_penalty * 2, self.max_score))
        return round(score, 1)

    def _get_top_issues(self, issues: list[Issue], limit: int = 10) -> list[Issue]:
        """Get top priority issues sorted by severity.

        Priority order: Critical > High > Medium > Low
        """
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
        }

        sorted_issues = sorted(
            issues,
            key=lambda i: (severity_order.get(Severity(i.severity), 4), i.category),
        )

        return sorted_issues[:limit]

    def generate_text_report(self, scan: ScanResult, summary: Optional[ScanSummary] = None) -> str:
        """Generate a plain text report.

        Args:
            scan: Complete scan result
            summary: Pre-calculated summary (optional)

        Returns:
            Formatted text report
        """
        if summary is None:
            summary = self.aggregate(scan)

        lines = [
            "=" * 80,
            "WEBSITE QUALITY REPORT",
            "=" * 80,
            "",
            f"URL: {scan.url}",
            f"Scan ID: {scan.id}",
            f"Date: {scan.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Duration: {scan.duration_seconds:.1f}s" if scan.duration_seconds else "",
            "",
            "-" * 40,
            "SUMMARY",
            "-" * 40,
            f"Overall Score: {summary.overall_score}/100",
            f"Pages Analyzed: {summary.pages_analyzed}/{summary.total_pages}",
            f"Total Issues: {summary.total_issues}",
            f"  Critical: {summary.critical_issues}",
            f"  High: {summary.high_issues}",
            f"  Medium: {summary.medium_issues}",
            f"  Low: {summary.low_issues}",
            "",
            "-" * 40,
            "SCORES BY CATEGORY",
            "-" * 40,
        ]

        for cat_score in summary.category_scores:
            if cat_score.issue_count > 0:
                lines.append(
                    f"  {cat_score.category.upper()}: {cat_score.score}/100 "
                    f"({cat_score.issue_count} issues)"
                )

        lines.extend([
            "",
            "-" * 40,
            "TOP PRIORITY ISSUES",
            "-" * 40,
        ])

        for i, issue in enumerate(summary.top_issues, 1):
            lines.extend([
                f"{i}. [{issue.severity.upper()}] {issue.title}",
                f"   URL: {issue.url}",
                f"   {issue.recommendation}",
                "",
            ])

        return "\n".join(lines)

    def generate_html_report(self, scan: ScanResult, summary: Optional[ScanSummary] = None) -> str:
        """Generate an HTML report.

        Args:
            scan: Complete scan result
            summary: Pre-calculated summary (optional)

        Returns:
            HTML report string
        """
        if summary is None:
            summary = self.aggregate(scan)

        severity_colors = {
            "critical": "#dc3545",
            "high": "#fd7e14",
            "medium": "#ffc107",
            "low": "#6c757d",
        }

        issues_html = ""
        for issue in summary.top_issues:
            color = severity_colors.get(issue.severity, "#6c757d")
            issues_html += f"""
            <div class="issue" style="border-left: 4px solid {color}; padding: 10px; margin: 10px 0; background: #f8f9fa;">
                <strong style="color: {color};">[{issue.severity.upper()}]</strong> {issue.title}
                <br><small>URL: {issue.url}</small>
                <br><em>{issue.recommendation}</em>
            </div>
            """

        category_html = ""
        for cat in summary.category_scores:
            if cat.issue_count > 0:
                category_html += f"""
                <tr>
                    <td>{cat.category.upper()}</td>
                    <td>{cat.score}/100</td>
                    <td>{cat.issue_count}</td>
                </tr>
                """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Website Quality Report - {scan.url}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
                h1 {{ color: #333; }}
                .score {{ font-size: 48px; font-weight: bold; color: #28a745; }}
                .summary {{ display: flex; gap: 20px; flex-wrap: wrap; }}
                .stat {{ background: #f8f9fa; padding: 15px; border-radius: 8px; min-width: 120px; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f8f9fa; }}
            </style>
        </head>
        <body>
            <h1>Website Quality Report</h1>
            <p><strong>URL:</strong> {scan.url}</p>
            <p><strong>Date:</strong> {scan.started_at.strftime('%Y-%m-%d %H:%M:%S')}</p>

            <h2>Overall Score</h2>
            <div class="score">{summary.overall_score}/100</div>

            <h2>Summary</h2>
            <div class="summary">
                <div class="stat"><strong>{summary.pages_analyzed}</strong><br>Pages Analyzed</div>
                <div class="stat"><strong>{summary.total_issues}</strong><br>Total Issues</div>
                <div class="stat" style="color: #dc3545;"><strong>{summary.critical_issues}</strong><br>Critical</div>
                <div class="stat" style="color: #fd7e14;"><strong>{summary.high_issues}</strong><br>High</div>
                <div class="stat" style="color: #ffc107;"><strong>{summary.medium_issues}</strong><br>Medium</div>
            </div>

            <h2>Scores by Category</h2>
            <table>
                <tr><th>Category</th><th>Score</th><th>Issues</th></tr>
                {category_html}
            </table>

            <h2>Top Priority Issues</h2>
            {issues_html}
        </body>
        </html>
        """
