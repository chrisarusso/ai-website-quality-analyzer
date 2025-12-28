"""Slack notification utilities for Website Quality Agent.

Sends notifications for scan start, completion, and failure.
"""

import json
import socket
from datetime import datetime
from typing import Optional

import httpx

from .config import SLACK_WEBHOOK_URL, API_BASE_URL


def get_hostname() -> str:
    """Get the current hostname for context in notifications."""
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def send_slack_notification(
    emoji: str,
    title: str,
    message: str,
    color: str = "good",
) -> bool:
    """Send a Slack notification via webhook.

    Args:
        emoji: Emoji to prefix the title (e.g., "🚀", "✅", "❌")
        title: Header text for the notification
        message: Body text (supports Slack mrkdwn formatting)
        color: Attachment color ("good", "warning", "danger", or hex)

    Returns:
        True if notification was sent successfully, False otherwise.
    """
    if not SLACK_WEBHOOK_URL:
        print(f"[Slack disabled] {title}: {message[:100]}...")
        return False

    hostname = get_hostname()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {title}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message,
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Server: `{hostname}` | Time: `{timestamp}`",
                    }
                ],
            },
        ],
    }

    try:
        response = httpx.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            timeout=10.0,
        )
        return response.status_code == 200
    except Exception as e:
        print(f"[Slack error] Failed to send notification: {e}")
        return False


def notify_scan_started(url: str, max_pages: int, scan_id: str) -> bool:
    """Send notification that a scan has started."""
    message = (
        f"*URL:* {url}\n"
        f"*Max Pages:* {max_pages}\n"
        f"*Scan ID:* `{scan_id}`"
    )
    return send_slack_notification("🚀", "Website Scan Started", message)


def notify_scan_completed(
    url: str,
    scan_id: str,
    pages_crawled: int,
    total_issues: int,
    overall_score: float,
    duration_seconds: int,
    report_file: Optional[str] = None,
) -> bool:
    """Send notification that a scan has completed successfully."""
    duration_min = duration_seconds // 60
    duration_sec = duration_seconds % 60

    # Build report URL from API_BASE_URL
    report_url = f"{API_BASE_URL}/api/scan/{scan_id}/report" if API_BASE_URL else None

    message = (
        f"*URL:* {url}\n"
        f"*Pages Crawled:* {pages_crawled}\n"
        f"*Total Issues:* {total_issues}\n"
        f"*Overall Score:* {overall_score:.1f}/100\n"
        f"*Duration:* {duration_min}m {duration_sec}s"
    )

    if report_url:
        message += f"\n*Report:* <{report_url}|View Report>"
    elif report_file:
        message += f"\n*Report:* `{report_file}`"

    return send_slack_notification("✅", "Website Scan Complete", message)


def notify_scan_failed(
    url: str,
    scan_id: str,
    error: str,
    duration_seconds: Optional[int] = None,
) -> bool:
    """Send notification that a scan has failed."""
    duration_min = (duration_seconds or 0) // 60
    duration_sec = (duration_seconds or 0) % 60

    # Truncate error if too long
    if len(error) > 500:
        error = error[:500] + "..."

    message = (
        f"*URL:* {url}\n"
        f"*Scan ID:* `{scan_id}`\n"
        f"*Error:* {error}"
    )

    if duration_seconds:
        message += f"\n*Duration:* {duration_min}m {duration_sec}s"

    return send_slack_notification("❌", "Website Scan FAILED", message, color="danger")
