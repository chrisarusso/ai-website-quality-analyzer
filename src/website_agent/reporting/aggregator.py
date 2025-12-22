from collections import Counter
from datetime import datetime
from typing import Dict, Iterable, List
from zoneinfo import ZoneInfo

from website_agent.config import get_settings
from website_agent.models import Issue, PageResult, ScanSummary, Severity


class Aggregator:
    def summarize(self, scan_id: int, root_url: str, pages: List[PageResult], issues: Iterable[Issue]) -> ScanSummary:
        issue_list = list(issues)
        issues_by_severity: Dict[Severity, int] = Counter([issue.severity for issue in issue_list])
        issues_by_category: Dict[str, int] = Counter([issue.category for issue in issue_list])
        top_messages = [issue.message for issue in issue_list[:5]]
        tz = ZoneInfo(get_settings().timezone)
        created_at = pages[0].fetched_at if pages else datetime.now(tz)

        return ScanSummary(
            scan_id=scan_id,
            root_url=root_url,
            created_at=created_at,
            page_count=len(pages),
            issue_count=len(issue_list),
            issues_by_severity=dict(issues_by_severity),
            issues_by_category=dict(issues_by_category),
            top_messages=top_messages,
        )

