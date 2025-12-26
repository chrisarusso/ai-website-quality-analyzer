"""Report aggregator for combining and scoring scan results.

Combines issues from all pages, calculates scores, and generates summaries.
"""

import hashlib
import html as html_module
from collections import defaultdict
from dataclasses import dataclass
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


@dataclass
class SiteWideIssue:
    """An issue that appears on most pages (site-wide)."""
    issue: Issue  # Representative issue
    page_count: int  # Number of pages this appears on
    pages: list[str]  # List of page URLs (for reference)


class ReportAggregator:
    """Aggregates scan results into summary reports."""

    # Threshold for considering an issue "site-wide" (appears on this % of pages)
    SITE_WIDE_THRESHOLD = 0.9  # 90%

    def __init__(self, max_score: float = 100.0):
        """Initialize aggregator.

        Args:
            max_score: Maximum possible score (default 100)
        """
        self.max_score = max_score

    def _get_issue_hash(self, issue: Issue) -> str:
        """Create a hash to identify similar issues across pages.

        Uses title and category to group issues. Does not use URL or element
        since those vary per page.
        """
        key = f"{issue.category}:{issue.title}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def _identify_site_wide_issues(
        self, all_issues: list[Issue], total_pages: int
    ) -> tuple[list[SiteWideIssue], list[Issue]]:
        """Separate site-wide issues from per-page issues.

        Args:
            all_issues: All issues from all pages
            total_pages: Total number of pages analyzed

        Returns:
            Tuple of (site_wide_issues, per_page_issues)
        """
        if total_pages < 2:
            return [], all_issues

        # Group issues by hash
        issues_by_hash: dict[str, list[Issue]] = defaultdict(list)
        for issue in all_issues:
            issue_hash = self._get_issue_hash(issue)
            issues_by_hash[issue_hash].append(issue)

        site_wide_issues = []
        per_page_issues = []
        threshold = total_pages * self.SITE_WIDE_THRESHOLD

        for issue_hash, issues in issues_by_hash.items():
            # Count unique pages this issue appears on
            unique_pages = list(set(i.url for i in issues))
            page_count = len(unique_pages)

            if page_count >= threshold:
                # This is a site-wide issue - use first occurrence as representative
                site_wide_issues.append(SiteWideIssue(
                    issue=issues[0],
                    page_count=page_count,
                    pages=unique_pages,
                ))
            else:
                # These are per-page issues
                per_page_issues.extend(issues)

        # Sort site-wide issues by severity then title
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        site_wide_issues.sort(
            key=lambda sw: (severity_order.get(sw.issue.severity, 4), sw.issue.title)
        )

        return site_wide_issues, per_page_issues

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

    def generate_html_report(
        self,
        scan: ScanResult,
        summary: Optional[ScanSummary] = None,
        issue_ids: Optional[dict[str, int]] = None,
        enable_fixes: bool = True,
    ) -> str:
        """Generate an HTML report with all issues.

        Args:
            scan: Complete scan result
            summary: Pre-calculated summary (optional)
            issue_ids: Optional mapping from issue hash to database ID
            enable_fixes: Whether to enable the fix UI (checkboxes, Run Fixes button)

        Returns:
            HTML report string
        """
        if summary is None:
            summary = self.aggregate(scan)

        # Global issue counter for generating unique IDs
        issue_counter = [0]  # Use list to allow mutation in nested function

        def get_issue_id(issue: Issue) -> str:
            """Generate a unique ID for an issue."""
            issue_counter[0] += 1
            # Create a hash-based ID for matching
            key = f"{issue.category}:{issue.severity}:{issue.title}:{issue.url}"
            issue_hash = hashlib.md5(key.encode()).hexdigest()[:8]
            return f"issue-{issue_counter[0]}-{issue_hash}"

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

        # Separate site-wide issues from per-page issues
        total_pages = len([p for p in scan.pages if p.status_code == 200])
        site_wide_issues, per_page_issues = self._identify_site_wide_issues(all_issues, total_pages)

        # Build pages list HTML
        pages_list_html = ""
        for i, page in enumerate(sorted(scan.pages, key=lambda p: p.url), 1):
            status_icon = "✅" if page.status_code == 200 else f"⚠️ {page.status_code}"
            issue_count = len(page.issues)
            issue_badge = f'<span style="background: #dc3545; color: white; padding: 2px 6px; border-radius: 10px; font-size: 0.8em; margin-left: 8px;">{issue_count}</span>' if issue_count > 0 else ""
            pages_list_html += f'''
            <div style="padding: 6px 0; border-bottom: 1px solid #eee; font-size: 0.9em;">
                <span style="color: #666; width: 40px; display: inline-block;">{i}.</span>
                {status_icon}
                <a href="{page.url}" target="_blank" style="color: #0066cc; text-decoration: none;">{page.url}</a>
                {issue_badge}
            </div>
            '''

        # Build site-wide issues section
        site_wide_html = ""
        if site_wide_issues:
            site_wide_items = ""
            for sw in site_wide_issues:
                issue = sw.issue
                color = severity_colors.get(issue.severity, "#6c757d")
                code_html = ""
                if issue.element:
                    escaped_element = html_module.escape(issue.element)
                    code_html = f'''
                    <div class="code-context">
                        <pre><code>{escaped_element}</code></pre>
                    </div>
                    '''
                site_wide_items += f"""
                <div class="issue severity-{issue.severity}" data-severity="{issue.severity}" style="border-left: 4px solid {color}; padding: 12px 15px; margin: 8px 0; background: #f8f9fa; border-radius: 0 4px 4px 0;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                        <div style="flex: 1;">
                            <strong style="color: {color};">[{issue.severity.upper()}]</strong> {issue.title}
                            <span style="background: #6c757d; color: white; padding: 2px 8px; border-radius: 10px; font-size: 0.75em; margin-left: 10px;">Appears on {sw.page_count} pages</span>
                        </div>
                    </div>
                    <div style="margin-top: 6px;">
                        <small style="color: #666;">Category: {issue.category.upper()}</small>
                    </div>
                    {code_html}
                    <div style="margin-top: 8px;">
                        <em style="color: #555; font-size: 0.9em;">💡 {issue.recommendation}</em>
                    </div>
                </div>
                """
            site_wide_html = f"""
            <div class="site-wide-section" style="margin-bottom: 30px;">
                <h2 style="color: #6c757d; border-bottom: 2px solid #6c757d; padding-bottom: 8px;">
                    🌐 Site-Wide Issues ({len(site_wide_issues)} issues affecting 90%+ of pages)
                </h2>
                <p style="color: #666; margin-bottom: 15px;">These issues appear on nearly every page. Fix them once at the template/theme level for maximum impact.</p>
                {site_wide_items}
            </div>
            """

        # Group remaining per-page issues by category
        issues_by_category: dict[str, list[Issue]] = defaultdict(list)
        for issue in per_page_issues:
            issues_by_category[issue.category].append(issue)

        # Sort issues within each category by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for category in issues_by_category:
            issues_by_category[category].sort(
                key=lambda i: (severity_order.get(i.severity, 4), i.url, i.title)
            )

        # Build category sections HTML (only per-page issues, site-wide shown separately)
        category_sections_html = ""
        for cat in summary.category_scores:
            cat_issues = issues_by_category.get(cat.category, [])
            if cat_issues:  # Only show categories that have per-page issues
                issues_html = ""
                for issue in cat_issues:
                    color = severity_colors.get(issue.severity, "#6c757d")
                    # Truncate long URLs for display
                    display_url = issue.url
                    if len(display_url) > 80:
                        display_url = display_url[:77] + "..."

                    # Build the HTML context/code snippet section
                    code_html = ""
                    if issue.element:
                        # Escape HTML for display
                        escaped_element = html_module.escape(issue.element)
                        code_html = f'''
                        <div class="code-context">
                            <pre><code>{escaped_element}</code></pre>
                        </div>
                        '''

                    # Generate unique ID for this issue
                    issue_id = get_issue_id(issue)
                    escaped_title = html_module.escape(issue.title).replace("'", "\\'").replace('"', '&quot;')

                    # Build fix controls HTML (checkbox + instruction input)
                    fix_controls_html = ""
                    if enable_fixes:
                        fix_controls_html = f'''
                        <div class="fix-controls">
                            <label class="fix-checkbox" style="display: flex; align-items: center; gap: 8px; font-size: 0.85em; color: #333; cursor: pointer;">
                                <input type="checkbox" class="issue-fix-checkbox"
                                    data-issue-id="{issue_id}"
                                    data-category="{issue.category}"
                                    data-severity="{issue.severity}"
                                    data-title="{escaped_title}"
                                    data-url="{issue.url}">
                                <span>🔧 Select for auto-fix</span>
                            </label>
                            <div class="fix-instructions hidden">
                                <textarea class="instruction-input" data-issue-id="{issue_id}"
                                    placeholder="Optional: Add context or instructions for the fix agent..."
                                    rows="2" maxlength="1000"></textarea>
                            </div>
                        </div>
                        '''

                    issues_html += f"""
                    <div class="issue severity-{issue.severity}" data-severity="{issue.severity}" data-issue-id="{issue_id}" style="border-left: 4px solid {color}; padding: 12px 15px; margin: 8px 0; background: #f8f9fa; border-radius: 0 4px 4px 0;">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <div style="flex: 1;">
                                <strong style="color: {color};">[{issue.severity.upper()}]</strong> {issue.title}
                            </div>
                        </div>
                        <div style="margin-top: 6px;">
                            <small style="color: #666;">URL: <a href="{issue.url}" target="_blank">{display_url}</a></small>
                        </div>
                        {code_html}
                        <div style="margin-top: 8px;">
                            <em style="color: #555; font-size: 0.9em;">💡 {issue.recommendation}</em>
                        </div>
                        {fix_controls_html}
                    </div>
                    """

                category_sections_html += f"""
                <div class="category-section" id="cat-{cat.category}">
                    <h3 onclick="toggleCategory('{cat.category}')" style="cursor: pointer; user-select: none;">
                        <span class="toggle-icon" id="icon-{cat.category}">▼</span>
                        {cat.category.upper()} ({len(cat_issues)} issues - Score: {cat.score}/100)
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
                .category-issues.hidden, .hidden {{ display: none; }}
                .issue a {{ color: #0066cc; text-decoration: none; }}
                .issue a:hover {{ text-decoration: underline; }}
                .nav-link {{ color: #0066cc; cursor: pointer; }}
                .nav-link:hover {{ text-decoration: underline; }}
                .code-context {{ margin: 10px 0; }}
                .code-context pre {{ background: #1e1e1e; color: #d4d4d4; padding: 12px 15px; border-radius: 6px; overflow-x: auto; margin: 0; font-size: 0.85em; line-height: 1.4; }}
                .code-context code {{ font-family: 'SF Mono', Consolas, 'Liberation Mono', Menlo, monospace; white-space: pre-wrap; word-break: break-word; }}
                .fix-controls {{ margin-top: 10px; border-top: 1px dashed #ddd; padding-top: 8px; }}
                .fix-checkbox {{ cursor: pointer; display: flex; align-items: center; gap: 8px; }}
                .fix-checkbox input {{ cursor: pointer; width: 18px; height: 18px; }}
                .fix-checkbox:hover {{ background: #f0f0f0; }}
                .fix-instructions {{ margin-top: 8px; }}
                .fix-instructions.hidden {{ display: none; }}
                .instruction-input {{
                    width: 100%;
                    padding: 8px;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    font-size: 0.9em;
                    resize: vertical;
                    font-family: inherit;
                }}
                .run-fixes-section {{
                    position: sticky;
                    bottom: 0;
                    background: white;
                    border-top: 2px solid #333;
                    padding: 20px;
                    margin-top: 30px;
                    box-shadow: 0 -4px 12px rgba(0,0,0,0.1);
                    z-index: 100;
                }}
                .run-fixes-btn {{
                    background: #28a745;
                    color: white;
                    border: none;
                    padding: 12px 24px;
                    font-size: 1.1em;
                    border-radius: 6px;
                    cursor: pointer;
                }}
                .run-fixes-btn:hover {{ background: #218838; }}
                .run-fixes-btn:disabled {{ background: #ccc; cursor: not-allowed; }}
                .selected-count {{ margin-left: 15px; font-size: 0.9em; color: #666; }}
                .progress-bar {{ background: #e9ecef; height: 20px; border-radius: 4px; overflow: hidden; }}
                .progress-fill {{ background: #28a745; height: 100%; transition: width 0.3s; }}
                @media print {{
                    .category-issues {{ display: block !important; }}
                    h3 {{ break-after: avoid; }}
                    .run-fixes-section {{ display: none; }}
                    .fix-controls {{ display: none; }}
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
                function togglePages() {{
                    const list = document.getElementById('pages-list');
                    const icon = document.getElementById('icon-pages');
                    if (list.classList.contains('hidden')) {{
                        list.classList.remove('hidden');
                        icon.textContent = '▼';
                    }} else {{
                        list.classList.add('hidden');
                        icon.textContent = '▶';
                    }}
                }}
                function filterBySeverity() {{
                    const showCritical = document.getElementById('filter-critical').checked;
                    const showHigh = document.getElementById('filter-high').checked;
                    const showMedium = document.getElementById('filter-medium').checked;
                    const showLow = document.getElementById('filter-low').checked;

                    document.querySelectorAll('.issue').forEach(issue => {{
                        const severity = issue.dataset.severity;
                        let show = false;
                        if (severity === 'critical' && showCritical) show = true;
                        if (severity === 'high' && showHigh) show = true;
                        if (severity === 'medium' && showMedium) show = true;
                        if (severity === 'low' && showLow) show = true;
                        issue.style.display = show ? 'block' : 'none';
                    }});

                    // Update category issue counts
                    document.querySelectorAll('.category-section').forEach(section => {{
                        const visibleIssues = section.querySelectorAll('.issue:not([style*="display: none"])').length;
                        const totalIssues = section.querySelectorAll('.issue').length;
                        const countSpan = section.querySelector('.visible-count');
                        if (countSpan) {{
                            countSpan.textContent = visibleIssues < totalIssues ? `${{visibleIssues}}/${{totalIssues}} shown` : `${{totalIssues}} issues`;
                        }}
                    }});
                }}

                // ==================== Fix Selection JavaScript ====================
                const selectedIssues = new Map();
                const SCAN_ID = '{scan.id}';

                function initFixControls() {{
                    // Show/hide instruction input when checkbox changes
                    document.querySelectorAll('.issue-fix-checkbox').forEach(checkbox => {{
                        checkbox.addEventListener('change', function() {{
                            const issueId = this.dataset.issueId;
                            const issueData = {{
                                category: this.dataset.category,
                                severity: this.dataset.severity,
                                title: this.dataset.title,
                                url: this.dataset.url,
                                instructions: ''
                            }};
                            const instructionDiv = this.closest('.fix-controls').querySelector('.fix-instructions');

                            if (this.checked) {{
                                instructionDiv.classList.remove('hidden');
                                selectedIssues.set(issueId, issueData);
                            }} else {{
                                instructionDiv.classList.add('hidden');
                                selectedIssues.delete(issueId);
                            }}
                            updateSelectedCount();
                        }});
                    }});

                    // Track instruction text
                    document.querySelectorAll('.instruction-input').forEach(textarea => {{
                        textarea.addEventListener('input', function() {{
                            const issueId = this.dataset.issueId;
                            if (selectedIssues.has(issueId)) {{
                                const data = selectedIssues.get(issueId);
                                data.instructions = this.value;
                                selectedIssues.set(issueId, data);
                            }}
                        }});
                    }});

                    // Select all fixable issues
                    const selectAllCheckbox = document.getElementById('select-all-fixable');
                    if (selectAllCheckbox) {{
                        selectAllCheckbox.addEventListener('change', function() {{
                            document.querySelectorAll('.issue-fix-checkbox').forEach(checkbox => {{
                                if (checkbox.checked !== this.checked) {{
                                    checkbox.checked = this.checked;
                                    checkbox.dispatchEvent(new Event('change'));
                                }}
                            }});
                        }});
                    }}
                }}

                function updateSelectedCount() {{
                    const count = selectedIssues.size;
                    const countEl = document.getElementById('selected-count');
                    const btn = document.getElementById('run-fixes-btn');
                    if (countEl) countEl.textContent = `${{count}} issue${{count !== 1 ? 's' : ''}} selected`;
                    if (btn) btn.disabled = count === 0;
                }}

                async function runFixes() {{
                    const githubRepo = document.getElementById('github-repo')?.value || 'savaslabs/savaslabs.com';

                    const issues = [];
                    selectedIssues.forEach((data, issueId) => {{
                        issues.push({{
                            issue_id: issueId,
                            category: data.category,
                            severity: data.severity,
                            title: data.title,
                            url: data.url,
                            user_instructions: data.instructions || null
                        }});
                    }});

                    if (issues.length === 0) {{
                        alert('Please select at least one issue to fix.');
                        return;
                    }}

                    // Confirmation dialog
                    const confirmMessage = `
⚠️ CONFIRM FIX SUBMISSION ⚠️

You are about to create GitHub issues/PRs for ${{issues.length}} selected issue(s).

TARGET REPOSITORY: ${{githubRepo}}

This will:
• Create GitHub issues in the repository above
• Attempt to create PRs for code fixes (if applicable)
• NOT modify any Drupal content (not yet implemented)

BEFORE PROCEEDING:
✓ Ensure you have a backup of the target repository
✓ Verify the target repo is correct (use POC repo for testing)
✓ Confirm you can close/delete test issues if needed

Do you want to proceed?`;

                    if (!confirm(confirmMessage)) {{
                        return;
                    }}

                    // Show progress
                    const progressDiv = document.getElementById('fix-progress');
                    const progressText = document.getElementById('progress-text');
                    const progressFill = document.getElementById('progress-fill');
                    const btn = document.getElementById('run-fixes-btn');

                    if (progressDiv) progressDiv.classList.remove('hidden');
                    if (progressText) progressText.textContent = 'Starting fix process...';
                    if (btn) btn.disabled = true;

                    try {{
                        const response = await fetch('/api/fix', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{
                                scan_id: SCAN_ID,
                                issues: issues,
                                github_repo: githubRepo,
                                create_github_issues: true
                            }})
                        }});

                        if (!response.ok) {{
                            throw new Error(`HTTP ${{response.status}}: ${{await response.text()}}`);
                        }}

                        const result = await response.json();

                        // Show results
                        if (progressFill) progressFill.style.width = '100%';
                        if (progressText) progressText.textContent = 'Complete!';

                        const resultsDiv = document.getElementById('fix-results');
                        if (resultsDiv) {{
                            resultsDiv.classList.remove('hidden');
                            resultsDiv.innerHTML = `
                                <h4 style="color: #28a745; margin-top: 15px;">Fixes Initiated</h4>
                                <ul>
                                    <li>Fixes created: ${{result.fixes_created}}</li>
                                    <li>GitHub issues created: ${{result.github_issues_created}}</li>
                                    <li>Batch ID: ${{result.fix_batch_id}}</li>
                                </ul>
                                <p>${{result.message}}</p>
                            `;
                        }}

                    }} catch (error) {{
                        if (progressText) progressText.textContent = `Error: ${{error.message}}`;
                        if (progressFill) progressFill.style.background = '#dc3545';
                    }}

                    if (btn) btn.disabled = false;
                }}

                // Initialize when DOM is ready
                document.addEventListener('DOMContentLoaded', initFixControls);
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

            <h2 onclick="togglePages()" style="cursor: pointer; user-select: none;">
                <span class="toggle-icon" id="icon-pages">▶</span>
                Pages Crawled ({len(scan.pages)} URLs)
            </h2>
            <div id="pages-list" class="pages-list hidden" style="background: #fff; border: 1px solid #e9ecef; padding: 15px; border-radius: 5px; max-height: 400px; overflow-y: auto; margin-bottom: 20px;">
                {pages_list_html}
            </div>

            {site_wide_html}

            <h2>Per-Page Issues by Category</h2>
            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                <strong>Filter by Severity:</strong>
                <label style="margin-left: 15px; cursor: pointer;">
                    <input type="checkbox" id="filter-critical" checked onchange="filterBySeverity()">
                    <span style="color: #dc3545;">Critical</span>
                </label>
                <label style="margin-left: 15px; cursor: pointer;">
                    <input type="checkbox" id="filter-high" checked onchange="filterBySeverity()">
                    <span style="color: #fd7e14;">High</span>
                </label>
                <label style="margin-left: 15px; cursor: pointer;">
                    <input type="checkbox" id="filter-medium" checked onchange="filterBySeverity()">
                    <span style="color: #ffc107;">Medium</span>
                </label>
                <label style="margin-left: 15px; cursor: pointer;">
                    <input type="checkbox" id="filter-low" onchange="filterBySeverity()">
                    <span style="color: #6c757d;">Low</span>
                </label>
                <span style="margin-left: 20px; color: #666;">|</span>
                <span class="nav-link" onclick="expandAll()" style="margin-left: 15px;">Expand All</span>
                <span style="color: #666;">|</span>
                <span class="nav-link" onclick="collapseAll()">Collapse All</span>
            </div>
            {category_sections_html}

            <hr style="margin-top: 40px;">

            <h2>Why These Issues Matter</h2>
            <p style="color: #666; margin-bottom: 15px;">Reference links explaining the importance of each issue type:</p>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px;">
                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
                    <h4 style="margin-top: 0; color: #333;">SEO Issues</h4>
                    <ul style="margin: 0; padding-left: 20px; font-size: 0.9em;">
                        <li><a href="https://developers.google.com/search/docs/fundamentals/seo-starter-guide" target="_blank">Google SEO Starter Guide</a></li>
                        <li><a href="https://developers.google.com/search/docs/appearance/title-link" target="_blank">Title Tags Best Practices</a></li>
                        <li><a href="https://developers.google.com/search/docs/appearance/snippet" target="_blank">Meta Descriptions Guide</a></li>
                        <li><a href="https://web.dev/articles/headings-and-landmarks" target="_blank">Heading Structure (H1-H6)</a></li>
                        <li><a href="https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls" target="_blank">Canonical URLs</a></li>
                        <li><a href="https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data" target="_blank">Structured Data (Schema.org)</a></li>
                    </ul>
                </div>

                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
                    <h4 style="margin-top: 0; color: #333;">Accessibility (WCAG)</h4>
                    <ul style="margin: 0; padding-left: 20px; font-size: 0.9em;">
                        <li><a href="https://www.w3.org/WAI/WCAG21/quickref/" target="_blank">WCAG 2.1 Quick Reference</a></li>
                        <li><a href="https://www.w3.org/WAI/tutorials/images/" target="_blank">Image Alt Text Guide</a></li>
                        <li><a href="https://www.w3.org/WAI/tutorials/forms/labels/" target="_blank">Form Labels Best Practices</a></li>
                        <li><a href="https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context" target="_blank">Link Text Requirements</a></li>
                        <li><a href="https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships" target="_blank">Heading Hierarchy</a></li>
                        <li><a href="https://www.w3.org/WAI/WCAG21/Understanding/language-of-page" target="_blank">Language Declaration</a></li>
                    </ul>
                </div>

                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
                    <h4 style="margin-top: 0; color: #333;">Performance</h4>
                    <ul style="margin: 0; padding-left: 20px; font-size: 0.9em;">
                        <li><a href="https://web.dev/articles/vitals" target="_blank">Core Web Vitals</a></li>
                        <li><a href="https://web.dev/articles/optimize-lcp" target="_blank">Largest Contentful Paint (LCP)</a></li>
                        <li><a href="https://web.dev/articles/cls" target="_blank">Cumulative Layout Shift (CLS)</a></li>
                        <li><a href="https://web.dev/articles/render-blocking-resources" target="_blank">Render-Blocking Resources</a></li>
                        <li><a href="https://web.dev/articles/browser-level-image-lazy-loading" target="_blank">Image Lazy Loading</a></li>
                    </ul>
                </div>

                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
                    <h4 style="margin-top: 0; color: #333;">Compliance & Security</h4>
                    <ul style="margin: 0; padding-left: 20px; font-size: 0.9em;">
                        <li><a href="https://gdpr.eu/cookies/" target="_blank">GDPR Cookie Requirements</a></li>
                        <li><a href="https://oag.ca.gov/privacy/ccpa" target="_blank">CCPA Compliance Guide</a></li>
                        <li><a href="https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP" target="_blank">Content Security Policy</a></li>
                        <li><a href="https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Strict-Transport-Security" target="_blank">HTTPS/HSTS Security</a></li>
                    </ul>
                </div>

                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
                    <h4 style="margin-top: 0; color: #333;">Mobile & Responsive</h4>
                    <ul style="margin: 0; padding-left: 20px; font-size: 0.9em;">
                        <li><a href="https://developers.google.com/search/docs/crawling-indexing/mobile/mobile-sites-mobile-first-indexing" target="_blank">Mobile-First Indexing</a></li>
                        <li><a href="https://web.dev/articles/responsive-web-design-basics" target="_blank">Responsive Web Design</a></li>
                        <li><a href="https://web.dev/articles/accessible-tap-targets" target="_blank">Touch Target Sizes</a></li>
                        <li><a href="https://developer.mozilla.org/en-US/docs/Web/HTML/Viewport_meta_tag" target="_blank">Viewport Meta Tag</a></li>
                    </ul>
                </div>

                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
                    <h4 style="margin-top: 0; color: #333;">Content Quality</h4>
                    <ul style="margin: 0; padding-left: 20px; font-size: 0.9em;">
                        <li><a href="https://developers.google.com/search/docs/fundamentals/creating-helpful-content" target="_blank">Google's Helpful Content</a></li>
                        <li><a href="https://www.nngroup.com/articles/writing-for-the-web/" target="_blank">Writing for the Web (NN Group)</a></li>
                        <li><a href="https://www.w3.org/WAI/WCAG21/Understanding/reading-level" target="_blank">Readability Requirements</a></li>
                    </ul>
                </div>
            </div>

            {'<div class="run-fixes-section" id="run-fixes-section">' if enable_fixes else ''}
            {'''
                <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 15px;">
                    <button class="run-fixes-btn" id="run-fixes-btn" onclick="runFixes()" disabled>
                        🔧 Run Fixes
                    </button>
                    <span id="selected-count" class="selected-count">0 issues selected</span>
                    <label style="margin-left: auto; cursor: pointer;">
                        <input type="checkbox" id="select-all-fixable">
                        Select all fixable issues
                    </label>
                </div>
                <div style="margin-top: 15px;">
                    <label style="font-size: 0.9em; color: #666;">
                        Target GitHub Repo:
                        <input type="text" id="github-repo" value="savaslabs/poc-savaslabs.com"
                            style="margin-left: 10px; padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; width: 250px;">
                    </label>
                    <span style="margin-left: 10px; color: #fd7e14; font-size: 0.85em;">⚠️ Use POC repo for testing</span>
                </div>
                <div id="fix-progress" class="hidden" style="margin-top: 15px;">
                    <div class="progress-bar">
                        <div id="progress-fill" class="progress-fill" style="width: 0%;"></div>
                    </div>
                    <p id="progress-text" style="margin: 8px 0 0 0; font-size: 0.9em; color: #666;"></p>
                </div>
                <div id="fix-results" class="hidden"></div>
            ''' if enable_fixes else ''}
            {'</div>' if enable_fixes else ''}

            <hr>
            <p style="color: #666; font-size: 0.9em;">
                Generated by Website Quality Agent v0.1.0
            </p>
        </body>
        </html>
        """
