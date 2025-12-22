"""Mobile responsiveness analyzer.

Checks for:
- Viewport meta tag
- Touch target sizes
- Responsive images
- Mobile-specific layout issues
- Text readability at mobile sizes
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

from ..models import Issue, IssueCategory, Severity
from .base import BaseAnalyzer


class MobileAnalyzer(BaseAnalyzer):
    """Analyzer for mobile responsiveness issues."""

    category = IssueCategory.MOBILE

    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[Issue]:
        """Analyze page for mobile responsiveness issues."""
        issues = []
        soup = self._get_soup(html, soup)

        issues.extend(self._check_viewport(soup, url))
        issues.extend(self._check_touch_targets(soup, url))
        issues.extend(self._check_responsive_images(soup, url))
        issues.extend(self._check_font_sizes(soup, url))
        issues.extend(self._check_horizontal_scroll(soup, url))

        return issues

    def _check_viewport(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for viewport meta tag."""
        issues = []
        viewport = soup.find("meta", attrs={"name": "viewport"})

        if not viewport:
            issues.append(self._create_issue(
                severity=Severity.HIGH,
                title="Missing viewport meta tag",
                description="No viewport meta tag found. Page will not scale properly on mobile.",
                recommendation='Add <meta name="viewport" content="width=device-width, initial-scale=1">',
                url=url,
            ))
        else:
            content = viewport.get("content", "")
            if "width=device-width" not in content:
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title="Viewport missing width=device-width",
                    description="Viewport should include width=device-width for proper mobile scaling.",
                    recommendation="Add width=device-width to the viewport content.",
                    url=url,
                ))

            if "user-scalable=no" in content or "maximum-scale=1" in content:
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title="Viewport disables zoom",
                    description="Viewport prevents users from zooming, which is an accessibility issue.",
                    recommendation="Remove user-scalable=no and maximum-scale=1 to allow zooming.",
                    url=url,
                ))

        return issues

    def _check_touch_targets(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for potentially small touch targets."""
        issues = []
        small_elements = []
        clickables = soup.find_all(["a", "button", "input"])

        for elem in clickables:
            style = elem.get("style", "")
            if style:
                width_match = re.search(r'width:\s*(\d+)px', style)
                height_match = re.search(r'height:\s*(\d+)px', style)
                if width_match and int(width_match.group(1)) < 44:
                    small_elements.append(elem)
                elif height_match and int(height_match.group(1)) < 44:
                    small_elements.append(elem)

        if len(small_elements) > 3:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"{len(small_elements)} potentially small touch targets",
                description="Some clickable elements may be too small for comfortable touch interaction.",
                recommendation="Ensure touch targets are at least 44x44 pixels.",
                url=url,
            ))

        return issues

    def _check_responsive_images(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for responsive image practices."""
        issues = []
        images = soup.find_all("img")

        if len(images) > 5:
            images_without_srcset = [img for img in images if not img.get("srcset")]
            if len(images_without_srcset) == len(images):
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="No responsive images (srcset)",
                    description="No images use srcset for responsive loading.",
                    recommendation="Use srcset to serve appropriately sized images for different screens.",
                    url=url,
                ))

        fixed_width_images = []
        for img in images:
            width = img.get("width", "")
            if width and width.isdigit() and int(width) > 400:
                fixed_width_images.append(img)

        if len(fixed_width_images) > 3:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"{len(fixed_width_images)} images with fixed large widths",
                description="Images with fixed pixel widths over 400px may cause horizontal scroll.",
                recommendation="Use max-width: 100% or responsive sizing for images.",
                url=url,
            ))

        return issues

    def _check_font_sizes(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for problematically small font sizes."""
        issues = []
        small_font_count = 0

        for elem in soup.find_all(style=True):
            style = elem.get("style", "")
            font_match = re.search(r'font-size:\s*(\d+)(px|pt)', style)
            if font_match:
                size = int(font_match.group(1))
                unit = font_match.group(2)
                if (unit == "px" and size < 12) or (unit == "pt" and size < 9):
                    small_font_count += 1

        if small_font_count > 5:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"{small_font_count} elements with small font size",
                description="Text smaller than 12px is difficult to read on mobile devices.",
                recommendation="Use a minimum font size of 16px for body text on mobile.",
                url=url,
            ))

        return issues

    def _check_horizontal_scroll(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for elements that might cause horizontal scroll."""
        issues = []

        tables = soup.find_all("table")
        for table in tables:
            parent = table.parent
            parent_style = parent.get("style", "") if parent else ""
            if "overflow" not in parent_style:
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="Table may cause horizontal scroll",
                    description="Tables without a responsive wrapper can overflow on mobile.",
                    recommendation="Wrap tables in a div with overflow-x: auto.",
                    url=url,
                ))
                break

        return issues
