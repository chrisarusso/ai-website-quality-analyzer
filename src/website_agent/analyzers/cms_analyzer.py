"""CMS security analyzer for detecting vulnerabilities.

Checks for:
- Drupal/WordPress version exposure
- Outdated CMS versions with known CVEs
- Exposed configuration files
- Admin panel exposure
- Plugin/module vulnerabilities
"""

import re
from typing import Optional, Tuple

from bs4 import BeautifulSoup

from ..models import Issue, IssueCategory, Severity
from .base import BaseAnalyzer


class CMSAnalyzer(BaseAnalyzer):
    """Analyzer for CMS security vulnerabilities."""

    category = IssueCategory.SECURITY

    # Known vulnerable versions (simplified - in production, use a CVE database)
    DRUPAL_VULNERABLE = {
        "7": ["7.0", "7.1", "7.2", "7.3", "7.4", "7.5"],  # SA-CORE examples
        "8": ["8.0", "8.1", "8.2", "8.3", "8.4", "8.5", "8.6"],
        "9": ["9.0", "9.1", "9.2"],
    }

    WORDPRESS_VULNERABLE = {
        "5": ["5.0", "5.1", "5.2", "5.3", "5.4"],
        "4": ["4.0", "4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9"],
    }

    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[Issue]:
        """Analyze page for CMS security issues."""
        issues = []
        soup = self._get_soup(html, soup)

        # Detect CMS
        cms, version = self._detect_cms(soup, html)

        if cms:
            issues.extend(self._check_version_exposure(cms, version, url))
            issues.extend(self._check_exposed_files(cms, url, soup))
            issues.extend(self._check_admin_exposure(cms, url, soup))
            issues.extend(self._check_generator_meta(soup, url))

        return issues

    def _detect_cms(self, soup: BeautifulSoup, html: str) -> Tuple[Optional[str], Optional[str]]:
        """Detect CMS type and version."""
        # Check for Drupal
        if self._is_drupal(soup, html):
            version = self._get_drupal_version(soup, html)
            return "drupal", version

        # Check for WordPress
        if self._is_wordpress(soup, html):
            version = self._get_wordpress_version(soup, html)
            return "wordpress", version

        # Check for Joomla
        if self._is_joomla(soup, html):
            return "joomla", None

        return None, None

    def _is_drupal(self, soup: BeautifulSoup, html: str) -> bool:
        """Check if site is Drupal."""
        indicators = [
            'name="Generator" content="Drupal',
            "Drupal.settings",
            "/sites/default/files",
            "/modules/",
            "drupal.js",
            'data-drupal-',
        ]
        return any(ind in html for ind in indicators)

    def _is_wordpress(self, soup: BeautifulSoup, html: str) -> bool:
        """Check if site is WordPress."""
        indicators = [
            'name="generator" content="WordPress',
            "/wp-content/",
            "/wp-includes/",
            "wp-json",
        ]
        return any(ind in html for ind in indicators)

    def _is_joomla(self, soup: BeautifulSoup, html: str) -> bool:
        """Check if site is Joomla."""
        indicators = [
            'name="generator" content="Joomla',
            "/media/jui/",
            "/components/com_",
        ]
        return any(ind in html for ind in indicators)

    def _get_drupal_version(self, soup: BeautifulSoup, html: str) -> Optional[str]:
        """Extract Drupal version if exposed."""
        # Check generator meta tag
        generator = soup.find("meta", attrs={"name": "Generator"})
        if generator:
            content = generator.get("content", "")
            match = re.search(r'Drupal\s+(\d+(?:\.\d+)*)', content)
            if match:
                return match.group(1)

        # Check for version in JavaScript
        match = re.search(r'Drupal\.settings.*?"version"\s*:\s*"(\d+\.\d+)"', html)
        if match:
            return match.group(1)

        return None

    def _get_wordpress_version(self, soup: BeautifulSoup, html: str) -> Optional[str]:
        """Extract WordPress version if exposed."""
        generator = soup.find("meta", attrs={"name": "generator"})
        if generator:
            content = generator.get("content", "")
            match = re.search(r'WordPress\s+(\d+(?:\.\d+)*)', content)
            if match:
                return match.group(1)

        # Check RSS feed link for version
        match = re.search(r'\?ver=(\d+\.\d+(?:\.\d+)?)', html)
        if match:
            return match.group(1)

        return None

    def _check_version_exposure(self, cms: str, version: Optional[str], url: str) -> list[Issue]:
        """Check for version exposure and known vulnerabilities."""
        issues = []

        if version:
            issues.append(self._create_issue(
                severity=Severity.MEDIUM,
                title=f"{cms.title()} version exposed: {version}",
                description=f"The {cms.title()} version ({version}) is publicly visible.",
                recommendation="Hide CMS version to reduce attack surface. Update to latest version.",
                url=url,
            ))

            # Check for known vulnerable versions
            if cms == "drupal":
                major = version.split(".")[0]
                if major in self.DRUPAL_VULNERABLE:
                    if version in self.DRUPAL_VULNERABLE[major]:
                        issues.append(self._create_issue(
                            severity=Severity.CRITICAL,
                            title=f"Vulnerable Drupal version: {version}",
                            description=f"Drupal {version} has known security vulnerabilities.",
                            recommendation="Immediately update to the latest Drupal version.",
                            url=url,
                        ))

            elif cms == "wordpress":
                major = version.split(".")[0]
                if major in self.WORDPRESS_VULNERABLE:
                    if version in self.WORDPRESS_VULNERABLE[major]:
                        issues.append(self._create_issue(
                            severity=Severity.CRITICAL,
                            title=f"Vulnerable WordPress version: {version}",
                            description=f"WordPress {version} has known security vulnerabilities.",
                            recommendation="Immediately update to the latest WordPress version.",
                            url=url,
                        ))

        return issues

    def _check_exposed_files(self, cms: str, url: str, soup: BeautifulSoup) -> list[Issue]:
        """Check for exposed configuration/sensitive files."""
        issues = []

        # Common exposed paths by CMS
        exposed_indicators = {
            "drupal": [
                "/sites/default/settings.php",
                "/sites/default/default.settings.php",
                "/CHANGELOG.txt",
                "/INSTALL.txt",
                "/README.txt",
                "/update.php",
            ],
            "wordpress": [
                "/wp-config.php",
                "/wp-config-sample.php",
                "/readme.html",
                "/license.txt",
                "/xmlrpc.php",
            ],
        }

        # Check HTML for references to sensitive files
        html = str(soup)
        cms_paths = exposed_indicators.get(cms, [])

        for path in cms_paths:
            if path in html:
                severity = Severity.HIGH if "config" in path or "settings" in path else Severity.MEDIUM
                issues.append(self._create_issue(
                    severity=severity,
                    title=f"Exposed file reference: {path}",
                    description=f"Reference to {path} found in page, may indicate exposed file.",
                    recommendation="Ensure sensitive files are not publicly accessible.",
                    url=url,
                    element=path,
                ))

        return issues

    def _check_admin_exposure(self, cms: str, url: str, soup: BeautifulSoup) -> list[Issue]:
        """Check for exposed admin interfaces."""
        issues = []

        admin_paths = {
            "drupal": ["/user/login", "/admin", "/user/register"],
            "wordpress": ["/wp-admin", "/wp-login.php"],
            "joomla": ["/administrator"],
        }

        html = str(soup)
        cms_admin = admin_paths.get(cms, [])

        for path in cms_admin:
            if path in html:
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title=f"Admin path referenced: {path}",
                    description=f"Link to admin area ({path}) found on page.",
                    recommendation="Consider hiding admin paths from public pages.",
                    url=url,
                ))
                break  # Report only once

        return issues

    def _check_generator_meta(self, soup: BeautifulSoup, url: str) -> list[Issue]:
        """Check for generator meta tag exposure."""
        issues = []

        generator = soup.find("meta", attrs={"name": re.compile(r"generator", re.I)})
        if generator:
            content = generator.get("content", "")
            if content:
                issues.append(self._create_issue(
                    severity=Severity.LOW,
                    title="Generator meta tag exposes CMS",
                    description=f"Meta generator tag reveals: {content}",
                    recommendation="Remove or obscure the generator meta tag.",
                    url=url,
                    element=f'<meta name="generator" content="{content}">',
                ))

        return issues
