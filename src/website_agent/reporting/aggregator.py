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

        # Calculate category scores (normalized by page count)
        page_count = len(scan.pages)
        category_scores = self._calculate_category_scores(all_issues, page_count)

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

    def _calculate_category_scores(
        self, issues: list[Issue], page_count: int = 1
    ) -> list[CategoryScore]:
        """Calculate scores for each category.

        Uses a logarithmic penalty curve to avoid flooring at 0 for sites
        with many issues. Normalizes by page count.
        """
        import math

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

            # Calculate weighted issue count
            weighted_issues = (
                critical * SEVERITY_WEIGHTS["critical"]
                + high * SEVERITY_WEIGHTS["high"]
                + medium * SEVERITY_WEIGHTS["medium"]
                + low * SEVERITY_WEIGHTS["low"]
            )

            # Normalize by page count (issues per page)
            issues_per_page = weighted_issues / max(page_count, 1)

            # Use logarithmic curve: score decreases as issues increase
            # 0 issues = 100, ~5 weighted issues/page = 50, ~50 weighted issues/page = 0
            if issues_per_page == 0:
                score = self.max_score
            else:
                # log curve: 100 - 20 * log2(1 + issues_per_page)
                penalty = 20 * math.log2(1 + issues_per_page)
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

        Uses a logarithmic penalty curve normalized by page count.
        This prevents scores from immediately flooring at 0.
        """
        import math

        if page_count == 0:
            return self.max_score

        total_weighted = 0
        for issue in issues:
            weight = SEVERITY_WEIGHTS.get(issue.severity, 1)
            total_weighted += weight

        # Normalize by page count (weighted issues per page)
        issues_per_page = total_weighted / page_count

        if issues_per_page == 0:
            return self.max_score

        # Logarithmic curve: 100 - 15 * log2(1 + issues_per_page)
        # 0 issues/page = 100, ~10 weighted issues/page = 50, ~100 weighted/page = 0
        penalty = 15 * math.log2(1 + issues_per_page)
        score = max(0, self.max_score - penalty)
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
        """Generate an HTML report with all issues.

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

        # Collect all issues from all pages
        all_issues = []
        for page in scan.pages:
            all_issues.extend(page.issues)

        # Group issues by category
        issues_by_category: dict[str, list[Issue]] = defaultdict(list)
        for issue in all_issues:
            issues_by_category[issue.category].append(issue)

        # Sort issues within each category by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for category in issues_by_category:
            issues_by_category[category].sort(
                key=lambda i: (severity_order.get(i.severity, 4), i.url, i.title)
            )

        # Build category sections HTML
        category_sections_html = ""
        for cat in summary.category_scores:
            if cat.issue_count > 0:
                cat_issues = issues_by_category.get(cat.category, [])
                issues_html = ""
                for issue in cat_issues:
                    color = severity_colors.get(issue.severity, "#6c757d")
                    # Truncate long URLs for display
                    display_url = issue.url
                    if len(display_url) > 80:
                        display_url = display_url[:77] + "..."
                    issues_html += f"""
                    <div class="issue" style="border-left: 4px solid {color}; padding: 8px 12px; margin: 6px 0; background: #f8f9fa;">
                        <strong style="color: {color};">[{issue.severity.upper()}]</strong> {issue.title}
                        <br><small style="color: #666;">URL: <a href="{issue.url}" target="_blank">{display_url}</a></small>
                        <br><em style="color: #555; font-size: 0.9em;">{issue.recommendation}</em>
                    </div>
                    """

                category_sections_html += f"""
                <div class="category-section" id="cat-{cat.category}">
                    <h3 onclick="toggleCategory('{cat.category}')" style="cursor: pointer; user-select: none;">
                        <span class="toggle-icon" id="icon-{cat.category}">▼</span>
                        {cat.category.upper()} ({cat.issue_count} issues - Score: {cat.score}/100)
                    </h3>
                    <div class="category-issues" id="issues-{cat.category}">
                        {issues_html}
                    </div>
                </div>
                """

        category_summary_html = ""
        for cat in summary.category_scores:
            if cat.issue_count > 0:
                category_summary_html += f"""
                <tr onclick="scrollToCategory('{cat.category}')" style="cursor: pointer;">
                    <td>{cat.category.upper()}</td>
                    <td>{cat.score}/100</td>
                    <td>{cat.issue_count}</td>
                </tr>
                """

        # Calculate score color
        score_color = "#28a745" if summary.overall_score >= 70 else (
            "#ffc107" if summary.overall_score >= 40 else "#dc3545"
        )

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Website Quality Report - {scan.url}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; line-height: 1.5; }}
                h1 {{ color: #333; border-bottom: 2px solid #333; padding-bottom: 10px; }}
                h2 {{ color: #444; margin-top: 30px; }}
                h3 {{ background: #e9ecef; padding: 12px 15px; margin: 15px 0 0 0; border-radius: 5px 5px 0 0; }}
                h3:hover {{ background: #dee2e6; }}
                .toggle-icon {{ display: inline-block; width: 20px; transition: transform 0.2s; }}
                .toggle-icon.collapsed {{ transform: rotate(-90deg); }}
                .score {{ font-size: 48px; font-weight: bold; }}
                .summary {{ display: flex; gap: 20px; flex-wrap: wrap; margin: 20px 0; }}
                .stat {{ background: #f8f9fa; padding: 15px 20px; border-radius: 8px; min-width: 120px; text-align: center; }}
                .stat strong {{ font-size: 24px; display: block; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f8f9fa; font-weight: 600; }}
                tr:hover {{ background: #f8f9fa; }}
                .category-section {{ margin-bottom: 5px; }}
                .category-issues {{ background: #fff; border: 1px solid #e9ecef; border-top: none; padding: 10px; border-radius: 0 0 5px 5px; }}
                .category-issues.hidden {{ display: none; }}
                .issue a {{ color: #0066cc; text-decoration: none; }}
                .issue a:hover {{ text-decoration: underline; }}
                .nav-link {{ color: #0066cc; cursor: pointer; }}
                .nav-link:hover {{ text-decoration: underline; }}
                @media print {{
                    .category-issues {{ display: block !important; }}
                    h3 {{ break-after: avoid; }}
                }}
            </style>
            <script>
                function toggleCategory(category) {{
                    const issues = document.getElementById('issues-' + category);
                    const icon = document.getElementById('icon-' + category);
                    if (issues.classList.contains('hidden')) {{
                        issues.classList.remove('hidden');
                        icon.classList.remove('collapsed');
                    }} else {{
                        issues.classList.add('hidden');
                        icon.classList.add('collapsed');
                    }}
                }}
                function scrollToCategory(category) {{
                    const section = document.getElementById('cat-' + category);
                    const issues = document.getElementById('issues-' + category);
                    const icon = document.getElementById('icon-' + category);
                    if (section) {{
                        section.scrollIntoView({{ behavior: 'smooth' }});
                        issues.classList.remove('hidden');
                        icon.classList.remove('collapsed');
                    }}
                }}
                function expandAll() {{
                    document.querySelectorAll('.category-issues').forEach(el => el.classList.remove('hidden'));
                    document.querySelectorAll('.toggle-icon').forEach(el => el.classList.remove('collapsed'));
                }}
                function collapseAll() {{
                    document.querySelectorAll('.category-issues').forEach(el => el.classList.add('hidden'));
                    document.querySelectorAll('.toggle-icon').forEach(el => el.classList.add('collapsed'));
                }}
            </script>
        </head>
        <body>
            <h1>Website Quality Report</h1>
            <p><strong>URL:</strong> <a href="{scan.url}" target="_blank">{scan.url}</a></p>
            <p><strong>Scan Date:</strong> {scan.started_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Duration:</strong> {f'{scan.duration_seconds:.1f}s' if scan.duration_seconds else 'N/A'}</p>

            <h2>Overall Score</h2>
            <div class="score" style="color: {score_color};">{summary.overall_score}/100</div>

            <h2>Summary</h2>
            <div class="summary">
                <div class="stat"><strong>{summary.pages_analyzed}</strong>Pages Analyzed</div>
                <div class="stat"><strong>{summary.total_issues}</strong>Total Issues</div>
                <div class="stat" style="color: #dc3545;"><strong>{summary.critical_issues}</strong>Critical</div>
                <div class="stat" style="color: #fd7e14;"><strong>{summary.high_issues}</strong>High</div>
                <div class="stat" style="color: #ffc107;"><strong>{summary.medium_issues}</strong>Medium</div>
                <div class="stat" style="color: #6c757d;"><strong>{summary.low_issues}</strong>Low</div>
            </div>

            <h2>Scores by Category</h2>
            <p><em>Click a category to jump to its issues</em></p>
            <table>
                <tr><th>Category</th><th>Score</th><th>Issues</th></tr>
                {category_summary_html}
            </table>

            <h2>All Issues by Category</h2>
            <p>
                <span class="nav-link" onclick="expandAll()">Expand All</span> |
                <span class="nav-link" onclick="collapseAll()">Collapse All</span>
            </p>
            {category_sections_html}

            <hr style="margin-top: 40px;">
            <p style="color: #666; font-size: 0.9em;">
                Generated by Website Quality Agent v0.1.0
            </p>
        </body>
        </html>
        """
