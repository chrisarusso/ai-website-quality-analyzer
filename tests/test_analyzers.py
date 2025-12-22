"""Tests for analyzer modules."""

import pytest
from bs4 import BeautifulSoup

from website_agent.analyzers import (
    SEOAnalyzer,
    AccessibilityAnalyzer,
    MobileAnalyzer,
    ComplianceAnalyzer,
    CMSAnalyzer,
    LinkAnalyzer,
    PerformanceAnalyzer,
)
from website_agent.models import Severity


class TestSEOAnalyzer:
    """Tests for SEO analyzer."""

    def setup_method(self):
        self.analyzer = SEOAnalyzer()

    def test_missing_title(self):
        """Test detection of missing title tag."""
        html = "<html><head></head><body><h1>Hello</h1></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "Hello", None)

        title_issues = [i for i in issues if "title" in i.title.lower()]
        assert len(title_issues) > 0
        assert any(i.severity == Severity.HIGH for i in title_issues)

    def test_missing_meta_description(self):
        """Test detection of missing meta description."""
        html = "<html><head><title>Test</title></head><body></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        meta_issues = [i for i in issues if "meta description" in i.title.lower()]
        assert len(meta_issues) > 0

    def test_missing_h1(self):
        """Test detection of missing H1."""
        html = "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "Content", None)

        h1_issues = [i for i in issues if "h1" in i.title.lower()]
        assert len(h1_issues) > 0

    def test_multiple_h1(self):
        """Test detection of multiple H1 tags."""
        html = "<html><head><title>Test</title></head><body><h1>First</h1><h1>Second</h1></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "First Second", None)

        h1_issues = [i for i in issues if "multiple h1" in i.title.lower()]
        assert len(h1_issues) > 0

    def test_valid_seo(self):
        """Test that valid SEO doesn't generate false positives."""
        html = """
        <html>
        <head>
            <title>My Great Page Title Here</title>
            <meta name="description" content="This is a great meta description that is between 150 and 160 characters long for optimal display in search results.">
            <link rel="canonical" href="https://example.com/page">
        </head>
        <body>
            <h1>Page Heading</h1>
            <p>Content here</p>
        </body>
        </html>
        """
        issues = self.analyzer.analyze("https://example.com/page", html, "Content", None)

        # Should not have missing title/description/h1 issues
        missing_issues = [i for i in issues if "missing" in i.title.lower()]
        # May still have minor issues like Open Graph, but no critical missing elements
        critical_missing = [i for i in missing_issues if i.severity == Severity.HIGH]
        assert len(critical_missing) == 0


class TestAccessibilityAnalyzer:
    """Tests for accessibility analyzer."""

    def setup_method(self):
        self.analyzer = AccessibilityAnalyzer()

    def test_image_missing_alt(self):
        """Test detection of images without alt text."""
        html = '<html><body><img src="test.jpg"></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        alt_issues = [i for i in issues if "alt" in i.title.lower()]
        assert len(alt_issues) > 0

    def test_image_with_alt(self):
        """Test that images with alt don't trigger issues."""
        html = '<html><body><img src="test.jpg" alt="Test image"></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        alt_issues = [i for i in issues if "alt" in i.title.lower() and "missing" in i.title.lower()]
        assert len(alt_issues) == 0

    def test_decorative_image(self):
        """Test that decorative images (empty alt) are OK."""
        html = '<html><body><img src="decoration.jpg" alt=""></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        alt_issues = [i for i in issues if "alt" in i.title.lower() and "missing" in i.title.lower()]
        assert len(alt_issues) == 0

    def test_missing_lang(self):
        """Test detection of missing language attribute."""
        html = "<html><body>Content</body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "Content", None)

        lang_issues = [i for i in issues if "language" in i.title.lower()]
        assert len(lang_issues) > 0

    def test_form_without_label(self):
        """Test detection of form inputs without labels."""
        html = '<html lang="en"><body><form><input type="text" name="email"></form></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        label_issues = [i for i in issues if "label" in i.title.lower()]
        assert len(label_issues) > 0


class TestMobileAnalyzer:
    """Tests for mobile analyzer."""

    def setup_method(self):
        self.analyzer = MobileAnalyzer()

    def test_missing_viewport(self):
        """Test detection of missing viewport meta tag."""
        html = "<html><head><title>Test</title></head><body></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        viewport_issues = [i for i in issues if "viewport" in i.title.lower()]
        assert len(viewport_issues) > 0

    def test_valid_viewport(self):
        """Test that valid viewport doesn't trigger issues."""
        html = '<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        missing_viewport = [i for i in issues if "missing viewport" in i.title.lower()]
        assert len(missing_viewport) == 0

    def test_zoom_disabled(self):
        """Test detection of disabled zoom."""
        html = '<html><head><meta name="viewport" content="width=device-width, user-scalable=no"></head><body></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        zoom_issues = [i for i in issues if "zoom" in i.title.lower()]
        assert len(zoom_issues) > 0


class TestComplianceAnalyzer:
    """Tests for compliance analyzer."""

    def setup_method(self):
        self.analyzer = ComplianceAnalyzer()

    def test_missing_privacy_policy(self):
        """Test detection of missing privacy policy."""
        html = "<html><body><a href='/about'>About</a></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        privacy_issues = [i for i in issues if "privacy" in i.title.lower()]
        assert len(privacy_issues) > 0

    def test_has_privacy_policy(self):
        """Test that privacy policy link is detected."""
        html = "<html><body><a href='/privacy-policy'>Privacy Policy</a></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        missing_privacy = [i for i in issues if "no privacy policy" in i.title.lower()]
        assert len(missing_privacy) == 0

    def test_tracking_detected(self):
        """Test detection of third-party tracking."""
        html = '<html><body><script src="https://www.google-analytics.com/analytics.js"></script></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        tracking_issues = [i for i in issues if "tracking" in i.title.lower()]
        assert len(tracking_issues) > 0


class TestCMSAnalyzer:
    """Tests for CMS analyzer."""

    def setup_method(self):
        self.analyzer = CMSAnalyzer()

    def test_drupal_detection(self):
        """Test Drupal CMS detection."""
        html = '<html><head><meta name="Generator" content="Drupal 9"></head><body></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        # Should detect Drupal
        drupal_issues = [i for i in issues if "drupal" in i.title.lower()]
        assert len(drupal_issues) > 0

    def test_wordpress_detection(self):
        """Test WordPress CMS detection."""
        html = '<html><head><meta name="generator" content="WordPress 6.0"></head><body></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        wp_issues = [i for i in issues if "wordpress" in i.title.lower()]
        assert len(wp_issues) > 0

    def test_no_cms(self):
        """Test that no CMS doesn't trigger issues."""
        html = "<html><head><title>Static Site</title></head><body></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        # Should not have CMS-specific issues
        cms_issues = [i for i in issues if "drupal" in i.title.lower() or "wordpress" in i.title.lower()]
        assert len(cms_issues) == 0


class TestLinkAnalyzer:
    """Tests for link analyzer."""

    def setup_method(self):
        self.analyzer = LinkAnalyzer()

    def test_thin_content(self):
        """Test detection of thin content."""
        html = "<html><body><p>Short</p></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "Short", None)

        thin_issues = [i for i in issues if "thin" in i.title.lower()]
        assert len(thin_issues) > 0

    def test_javascript_links(self):
        """Test detection of javascript: links."""
        html = '<html><body><a href="javascript:void(0)">Click</a></body></html>'
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        js_issues = [i for i in issues if "javascript" in i.title.lower()]
        assert len(js_issues) > 0


class TestPerformanceAnalyzer:
    """Tests for performance analyzer."""

    def setup_method(self):
        self.analyzer = PerformanceAnalyzer(use_lighthouse=False)

    def test_large_page(self):
        """Test detection of large page size."""
        # Create HTML larger than 200KB
        html = "<html><body>" + "x" * 250000 + "</body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        size_issues = [i for i in issues if "size" in i.title.lower()]
        assert len(size_issues) > 0

    def test_many_resources(self):
        """Test detection of too many resources."""
        scripts = "".join([f'<script src="script{i}.js"></script>' for i in range(60)])
        html = f"<html><head>{scripts}</head><body></body></html>"
        issues = self.analyzer.analyze("https://example.com", html, "", None)

        resource_issues = [i for i in issues if "request" in i.title.lower()]
        assert len(resource_issues) > 0

    def test_slow_load_time(self):
        """Test detection of slow load time."""
        html = "<html><body>Content</body></html>"
        # Pass load_time_ms via the analyze method signature if supported
        # For now, the PerformanceAnalyzer.analyze has a load_time_ms parameter
        issues = self.analyzer.analyze("https://example.com", html, "Content", None, load_time_ms=12000)

        slow_issues = [i for i in issues if "slow" in i.title.lower() or "load" in i.title.lower()]
        assert len(slow_issues) > 0
