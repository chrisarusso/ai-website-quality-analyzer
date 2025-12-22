"""Compliance analyzer for GDPR and privacy considerations.

Checks for:
- Cookie consent mechanism
- Privacy policy presence
- Accessibility statement
- Third-party tracking disclosure
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

from ..models import Issue, IssueCategory, Severity
from .base import BaseAnalyzer


class ComplianceAnalyzer(BaseAnalyzer):
    """Analyzer for compliance and privacy issues."""

    category = IssueCategory.COMPLIANCE

    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[Issue]:
        """Analyze page for compliance issues."""
        issues = []
        soup = self._get_soup(html, soup)

        issues.extend(self._check_cookie_consent(soup, html, url))
        issues.extend(self._check_privacy_policy(soup, url))
        issues.extend(self._check_accessibility_statement(soup, url))
        issues.extend(self._check_third_party_tracking(soup, url))

        return issues

    def _check_cookie_consent(self, soup: BeautifulSoup, html: str, url: str) -> list[Issue]:
        """Check for cookie consent mechanism."""
        issues = []

        consent_indicators = [
            "cookie-consent", "cookie-banner", "cookie-notice", "gdpr-consent",
            "consent-banner", "cookieconsent", "CookieConsent", "Cookiebot",
            "OneTrust", "TrustArc", "iubenda", "termly", "osano",
        ]

        html_lower = html.lower()
        has_consent = any(ind.lower() in html_lower for ind in consent_indicators)

        if not has_consent:
            sets_cookies = "document.cookie" in html or "setCookie" in html
            severity = Severity.HIGH if sets_cookies else Severity.MEDIUM

            issues.append(self._create_issue(
                severity=severity,
                title="No cookie consent mechanism detected",
                description="No cookie consent banner or mechanism was detected.",
                recommendation="Implement a cookie consent banner for GDPR/CCPA compliance.",
                url=url,
            ))

        return issues

    def _check_privacy_policy(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for privacy policy link."""
        issues = []

        privacy_patterns = [r"privacy\s*policy", r"privacy\s*notice", r"data\s*protection"]
        links = soup.find_all("a", href=True)
        has_privacy = False

        for link in links:
            link_text = link.get_text(strip=True).lower()
            href = link.get("href", "").lower()
            for pattern in privacy_patterns:
                if re.search(pattern, link_text) or re.search(pattern, href):
                    has_privacy = True
                    break
            if has_privacy:
                break

        if not has_privacy:
            issues.append(self._create_issue(
                severity=Severity.HIGH,
                title="No privacy policy link found",
                description="No link to a privacy policy was detected on the page.",
                recommendation="Add a clearly visible link to your privacy policy in the footer.",
                url=url,
            ))

        return issues

    def _check_accessibility_statement(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for accessibility statement link."""
        issues = []

        links = soup.find_all("a", href=True)
        has_a11y = False

        for link in links:
            link_text = link.get_text(strip=True).lower()
            href = link.get("href", "").lower()
            if "accessibility" in link_text or "accessibility" in href:
                has_a11y = True
                break

        if not has_a11y:
            issues.append(self._create_issue(
                severity=Severity.LOW,
                title="No accessibility statement found",
                description="No link to an accessibility statement was detected.",
                recommendation="Consider adding an accessibility statement for WCAG compliance transparency.",
                url=url,
            ))

        return issues

    def _check_third_party_tracking(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for third-party tracking scripts."""
        issues = []

        tracking_domains = [
            "google-analytics.com", "googletagmanager.com",
            "facebook.net", "hotjar.com", "clarity.ms",
            "mixpanel.com", "segment.com", "hubspot.com",
        ]

        scripts = soup.find_all("script", src=True)
        detected = []

        for script in scripts:
            src = script.get("src", "").lower()
            for domain in tracking_domains:
                if domain in src and domain not in detected:
                    detected.append(domain.split(".")[0])

        if detected:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"Third-party tracking detected ({len(detected)} services)",
                description=f"Detected: {', '.join(detected)}",
                recommendation="Ensure tracking is disclosed in privacy policy and consent obtained.",
                url=url,
            ))

        return issues
