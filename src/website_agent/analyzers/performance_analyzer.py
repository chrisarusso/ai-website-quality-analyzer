"""Performance analyzer using Lighthouse-style metrics.

Checks for:
- Page load time
- Time to First Byte (TTFB)
- Resource optimization opportunities
- Large page size
- Too many requests
"""

import json
import logging
import re
import subprocess
from typing import Optional

from bs4 import BeautifulSoup

from ..config import LIGHTHOUSE_PATH
from ..models import Issue, IssueCategory, Severity
from .base import BaseAnalyzer

logger = logging.getLogger(__name__)


class PerformanceAnalyzer(BaseAnalyzer):
    """Analyzer for performance issues."""

    category = IssueCategory.PERFORMANCE

    def __init__(self, use_lighthouse: bool = True):
        """Initialize performance analyzer.

        Args:
            use_lighthouse: Whether to try using Lighthouse CLI
        """
        self.use_lighthouse = use_lighthouse

    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
        load_time_ms: float = 0.0,
    ) -> list[Issue]:
        """Analyze page for performance issues."""
        issues = []
        soup = self._get_soup(html, soup)

        # Basic checks that don't require Lighthouse
        issues.extend(self._check_page_size(html, url))
        issues.extend(self._check_resource_count(soup, url))
        issues.extend(self._check_render_blocking(soup, url))
        issues.extend(self._check_image_optimization(soup, url))
        issues.extend(self._check_load_time(load_time_ms, url))

        return issues

    def analyze_with_lighthouse(self, url: str) -> list[Issue]:
        """Run Lighthouse and extract performance issues.

        This is a separate method because Lighthouse requires network access
        and takes significant time to run.
        """
        issues = []

        try:
            result = subprocess.run(
                [
                    LIGHTHOUSE_PATH,
                    url,
                    "--output=json",
                    "--quiet",
                    "--chrome-flags=--headless",
                    "--only-categories=performance",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.warning(f"Lighthouse failed for {url}: {result.stderr}")
                return issues

            data = json.loads(result.stdout)
            issues.extend(self._parse_lighthouse_results(data, url))

        except FileNotFoundError:
            logger.warning("Lighthouse CLI not found. Install with: npm install -g lighthouse")
        except subprocess.TimeoutExpired:
            logger.warning(f"Lighthouse timed out for {url}")
        except Exception as e:
            logger.error(f"Lighthouse error for {url}: {e}")

        return issues

    def _check_page_size(self, html: str, url: str) -> list[Issue]:
        """Check if page HTML is too large."""
        issues = []

        size_kb = len(html.encode("utf-8")) / 1024

        if size_kb > 500:
            issues.append(self._create_issue(
                severity=Severity.HIGH,
                title=f"Very large page size ({size_kb:.0f} KB)",
                description="HTML document is over 500 KB, which can significantly slow loading.",
                recommendation="Reduce HTML size by removing unused content, optimizing inline resources.",
                url=url,
            ))
        elif size_kb > 200:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"Large page size ({size_kb:.0f} KB)",
                description="HTML document is over 200 KB, which may impact loading performance.",
                recommendation="Consider reducing page size for faster loading.",
                url=url,
            ))

        return issues

    def _check_resource_count(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for too many resource requests."""
        issues = []

        scripts = soup.find_all("script", src=True)
        styles = soup.find_all("link", rel="stylesheet")
        images = soup.find_all("img", src=True)

        total = len(scripts) + len(styles) + len(images)

        if total > 100:
            issues.append(self._create_issue(
                severity=Severity.HIGH,
                title=f"Too many resource requests ({total})",
                description=f"Page loads {len(scripts)} scripts, {len(styles)} stylesheets, {len(images)} images.",
                recommendation="Reduce requests by bundling scripts/styles and lazy-loading images.",
                url=url,
            ))
        elif total > 50:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"Many resource requests ({total})",
                description=f"Page loads {len(scripts)} scripts, {len(styles)} stylesheets, {len(images)} images.",
                recommendation="Consider reducing the number of requests for better performance.",
                url=url,
            ))

        return issues

    def _check_render_blocking(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for render-blocking resources in head."""
        issues = []

        head = soup.find("head")
        if not head:
            return issues

        # Check for non-async/defer scripts in head
        blocking_scripts = []
        for script in head.find_all("script", src=True):
            if not script.get("async") and not script.get("defer"):
                blocking_scripts.append(script.get("src", "")[:50])

        if len(blocking_scripts) > 3:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"{len(blocking_scripts)} render-blocking scripts",
                description="Scripts in <head> without async/defer block page rendering.",
                recommendation="Add async or defer attribute to scripts, or move them to end of body.",
                url=url,
                context=", ".join(blocking_scripts[:3]) + "...",
            ))

        # Check for stylesheets without media queries
        stylesheets = head.find_all("link", rel="stylesheet")
        non_critical = [s for s in stylesheets if not s.get("media") or s.get("media") == "all"]

        if len(non_critical) > 5:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title=f"{len(non_critical)} stylesheets may block rendering",
                description="Multiple stylesheets load synchronously, potentially delaying render.",
                recommendation="Consider inlining critical CSS and loading non-critical styles async.",
                url=url,
            ))

        return issues

    def _check_image_optimization(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for image optimization opportunities."""
        issues = []

        images = soup.find_all("img", src=True)

        # Check for missing dimensions
        no_dimensions = [img for img in images if not img.get("width") or not img.get("height")]
        if len(no_dimensions) > 5:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"{len(no_dimensions)} images without dimensions",
                description="Images without width/height cause layout shift (CLS) when loading.",
                recommendation="Add width and height attributes to all images.",
                url=url,
            ))

        # Check for lazy loading
        images_in_body = [img for img in images if not img.find_parent("noscript")]
        no_lazy = [img for img in images_in_body if not img.get("loading")]
        if len(no_lazy) > 10:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title=f"{len(no_lazy)} images could use lazy loading",
                description="Images without loading='lazy' load immediately, slowing initial page load.",
                recommendation="Add loading='lazy' to images below the fold.",
                url=url,
            ))

        # Check for modern formats
        old_format_count = 0
        for img in images:
            src = img.get("src", "").lower()
            if src.endswith((".jpg", ".jpeg", ".png", ".gif")) and not src.startswith("data:"):
                old_format_count += 1

        if old_format_count > 10:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title=f"{old_format_count} images could use modern formats",
                description="Images in JPEG/PNG/GIF format could be smaller as WebP or AVIF.",
                recommendation="Consider converting images to WebP or AVIF for better compression.",
                url=url,
            ))

        return issues

    def _check_load_time(self, load_time_ms: float, url: str) -> list[Issue]:
        """Check page load time."""
        issues = []

        if load_time_ms <= 0:
            return issues

        load_time_s = load_time_ms / 1000

        if load_time_s > 10:
            issues.append(self._create_issue(
                severity=Severity.HIGH,
                title=f"Very slow page load ({load_time_s:.1f}s)",
                description="Page took over 10 seconds to load, which severely impacts user experience.",
                recommendation="Investigate performance bottlenecks and optimize resource loading.",
                url=url,
            ))
        elif load_time_s > 5:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"Slow page load ({load_time_s:.1f}s)",
                description="Page took over 5 seconds to load, which may frustrate users.",
                recommendation="Optimize resources and consider lazy loading to improve load time.",
                url=url,
            ))
        elif load_time_s > 3:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title=f"Page load could be faster ({load_time_s:.1f}s)",
                description="Page load time exceeds the recommended 3 second threshold.",
                recommendation="Consider performance optimizations to improve user experience.",
                url=url,
            ))

        return issues

    def _parse_lighthouse_results(self, data: dict, url: str) -> list[Issue]:
        """Parse Lighthouse JSON output into issues."""
        issues = []

        audits = data.get("audits", {})

        # Map Lighthouse audits to our issues
        audit_mappings = {
            "first-contentful-paint": ("First Contentful Paint", Severity.MEDIUM),
            "largest-contentful-paint": ("Largest Contentful Paint", Severity.HIGH),
            "cumulative-layout-shift": ("Cumulative Layout Shift", Severity.MEDIUM),
            "total-blocking-time": ("Total Blocking Time", Severity.MEDIUM),
            "speed-index": ("Speed Index", Severity.MEDIUM),
        }

        for audit_id, (title_prefix, default_severity) in audit_mappings.items():
            audit = audits.get(audit_id, {})
            score = audit.get("score")

            if score is not None and score < 0.9:
                display_value = audit.get("displayValue", "")
                severity = Severity.HIGH if score < 0.5 else default_severity

                issues.append(self._create_issue(
                    severity=severity,
                    title=f"{title_prefix}: {display_value}",
                    description=audit.get("description", ""),
                    recommendation="See Lighthouse report for detailed recommendations.",
                    url=url,
                ))

        return issues
