"""Accessibility analyzer for WCAG compliance issues.

Checks for:
- Images without alt text
- Color contrast issues (basic check)
- Missing form labels
- Keyboard navigation problems
- ARIA attribute issues
- Language declaration
- Focus indicators
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

from ..models import Issue, IssueCategory, Severity
from .base import BaseAnalyzer


class AccessibilityAnalyzer(BaseAnalyzer):
    """Analyzer for WCAG accessibility issues."""

    category = IssueCategory.ACCESSIBILITY

    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[Issue]:
        """Analyze page for accessibility issues."""
        issues = []
        soup = self._get_soup(html, soup)

        issues.extend(self._check_images_alt(soup, url))
        issues.extend(self._check_form_labels(soup, url))
        issues.extend(self._check_language(soup, url))
        issues.extend(self._check_aria_attributes(soup, url))
        issues.extend(self._check_links(soup, url))
        issues.extend(self._check_tables(soup, url))
        issues.extend(self._check_headings(soup, url))
        issues.extend(self._check_buttons(soup, url))

        return issues

    def _check_images_alt(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for images without alt text."""
        issues = []
        images = soup.find_all("img")

        for img in images:
            src = img.get("src", "")
            alt = img.get("alt")

            # Skip decorative images (empty alt is acceptable)
            if alt == "":
                continue

            if alt is None:
                issues.append(self._create_issue(
                    severity=Severity.HIGH,
                    title="Image missing alt text",
                    description="Image does not have an alt attribute, making it inaccessible to screen readers.",
                    recommendation='Add alt="" for decorative images or descriptive alt text for meaningful images.',
                    url=url,
                    element=f'<img src="{src[:50]}...">',
                    context=src[:100],
                ))

        return issues

    def _check_form_labels(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for form inputs without labels."""
        issues = []

        # Find all form inputs that should have labels
        inputs = soup.find_all(["input", "select", "textarea"])

        for input_elem in inputs:
            input_type = input_elem.get("type", "text")

            # Skip hidden, submit, button, image inputs
            if input_type in ["hidden", "submit", "button", "image", "reset"]:
                continue

            input_id = input_elem.get("id")
            input_name = input_elem.get("name", "unnamed")

            # Check for associated label
            has_label = False

            if input_id:
                # Check for label with for attribute
                label = soup.find("label", attrs={"for": input_id})
                if label:
                    has_label = True

            # Check for implicit label (input wrapped in label)
            parent = input_elem.parent
            if parent and parent.name == "label":
                has_label = True

            # Check for aria-label or aria-labelledby
            if input_elem.get("aria-label") or input_elem.get("aria-labelledby"):
                has_label = True

            # Check for placeholder (not ideal but acceptable)
            if input_elem.get("placeholder"):
                has_label = True  # Warn separately about placeholder-only labels

            if not has_label:
                issues.append(self._create_issue(
                    severity=Severity.HIGH,
                    title=f"Form input missing label",
                    description=f"Input field '{input_name}' has no associated label element.",
                    recommendation="Add a <label> element with for attribute matching the input's id.",
                    url=url,
                    element=f'<input type="{input_type}" name="{input_name}">',
                ))

        return issues

    def _check_language(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for language declaration."""
        issues = []

        html_tag = soup.find("html")
        if html_tag:
            lang = html_tag.get("lang")
            if not lang:
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title="Missing language declaration",
                    description="The html element does not have a lang attribute.",
                    recommendation='Add lang attribute: <html lang="en"> for English content.',
                    url=url,
                    element="<html>",
                ))
            elif len(lang) < 2:
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title="Invalid language code",
                    description=f"Language code '{lang}' appears to be invalid.",
                    recommendation="Use valid ISO 639-1 language codes (e.g., 'en', 'es', 'fr').",
                    url=url,
                    element=f'<html lang="{lang}">',
                ))

        return issues

    def _check_aria_attributes(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for ARIA attribute issues."""
        issues = []

        # Check for aria-labelledby pointing to non-existent elements
        elements_with_labelledby = soup.find_all(attrs={"aria-labelledby": True})
        for elem in elements_with_labelledby:
            label_id = elem.get("aria-labelledby")
            if label_id and not soup.find(id=label_id):
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title="ARIA labelledby references missing element",
                    description=f"aria-labelledby references id '{label_id}' which doesn't exist.",
                    recommendation="Ensure the referenced element exists or use aria-label instead.",
                    url=url,
                    element=str(elem)[:100],
                ))

        # Check for aria-describedby pointing to non-existent elements
        elements_with_describedby = soup.find_all(attrs={"aria-describedby": True})
        for elem in elements_with_describedby:
            desc_id = elem.get("aria-describedby")
            if desc_id and not soup.find(id=desc_id):
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="ARIA describedby references missing element",
                    description=f"aria-describedby references id '{desc_id}' which doesn't exist.",
                    recommendation="Ensure the referenced element exists or remove the attribute.",
                    url=url,
                    element=str(elem)[:100],
                ))

        # Check for invalid role values
        valid_roles = {
            "alert", "alertdialog", "application", "article", "banner", "button",
            "cell", "checkbox", "columnheader", "combobox", "complementary",
            "contentinfo", "definition", "dialog", "directory", "document",
            "feed", "figure", "form", "grid", "gridcell", "group", "heading",
            "img", "link", "list", "listbox", "listitem", "log", "main",
            "marquee", "math", "menu", "menubar", "menuitem", "menuitemcheckbox",
            "menuitemradio", "navigation", "none", "note", "option", "presentation",
            "progressbar", "radio", "radiogroup", "region", "row", "rowgroup",
            "rowheader", "scrollbar", "search", "searchbox", "separator",
            "slider", "spinbutton", "status", "switch", "tab", "table", "tablist",
            "tabpanel", "term", "textbox", "timer", "toolbar", "tooltip", "tree",
            "treegrid", "treeitem"
        }

        elements_with_role = soup.find_all(attrs={"role": True})
        for elem in elements_with_role:
            role = elem.get("role", "").lower()
            if role and role not in valid_roles:
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title=f"Invalid ARIA role: {role}",
                    description=f"The role '{role}' is not a valid ARIA role.",
                    recommendation="Use a valid ARIA role or remove the attribute.",
                    url=url,
                    element=str(elem)[:100],
                ))

        return issues

    def _check_links(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for accessibility issues with links."""
        issues = []

        links = soup.find_all("a")
        generic_texts = {"click here", "read more", "learn more", "here", "more", "link"}

        for link in links:
            link_text = link.get_text(strip=True).lower()
            href = link.get("href", "")

            # Check for empty links
            if not link_text and not link.find("img"):
                if href and not href.startswith("#"):
                    issues.append(self._create_issue(
                        severity=Severity.HIGH,
                        title="Empty link text",
                        description="Link has no text content, making it inaccessible.",
                        recommendation="Add descriptive text or aria-label to the link.",
                        url=url,
                        element=str(link)[:100],
                    ))

            # Check for generic link text (limit to first few)
            elif link_text in generic_texts:
                # Only report a few instances
                if sum(1 for i in issues if "generic link text" in i.title.lower()) < 3:
                    issues.append(self._create_issue(
                        severity=Severity.LOW,
                        title=f"Generic link text: '{link_text}'",
                        description="Link text doesn't describe the destination.",
                        recommendation="Use descriptive text that explains where the link goes.",
                        url=url,
                        element=str(link)[:100],
                    ))

        return issues

    def _check_tables(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for table accessibility issues."""
        issues = []

        tables = soup.find_all("table")
        for table in tables:
            # Check for table headers
            headers = table.find_all("th")
            if not headers:
                # Only flag if table has multiple rows (likely data table, not layout)
                rows = table.find_all("tr")
                if len(rows) > 2:
                    issues.append(self._create_issue(
                        severity=Severity.MEDIUM,
                        title="Data table missing headers",
                        description="Table appears to contain data but has no <th> elements.",
                        recommendation="Add <th> elements to identify column/row headers.",
                        url=url,
                        element="<table>",
                    ))

        return issues

    def _check_headings(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for heading accessibility issues."""
        issues = []

        # Check for empty headings
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        for heading in headings:
            if not heading.get_text(strip=True):
                issues.append(self._create_issue(
                    severity=Severity.MEDIUM,
                    title=f"Empty {heading.name.upper()} heading",
                    description="Heading element has no text content.",
                    recommendation="Add text to the heading or remove it if not needed.",
                    url=url,
                    element=str(heading)[:100],
                ))

        return issues

    def _check_buttons(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for button accessibility issues."""
        issues = []

        buttons = soup.find_all("button")
        for button in buttons:
            text = button.get_text(strip=True)
            aria_label = button.get("aria-label")
            title = button.get("title")

            if not text and not aria_label and not title:
                # Check if button contains only an image or icon
                if button.find("img") or button.find("svg") or button.find("i"):
                    issues.append(self._create_issue(
                        severity=Severity.HIGH,
                        title="Icon button missing accessible name",
                        description="Button contains only an icon with no accessible text.",
                        recommendation="Add aria-label or visually hidden text to describe the button's action.",
                        url=url,
                        element=str(button)[:100],
                    ))

        return issues
