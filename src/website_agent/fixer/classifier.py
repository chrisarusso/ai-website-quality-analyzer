"""Fix classifier for categorizing issues by how they can be fixed.

Classifies issues into:
- CODE_FIX: Can be fixed via Git PR (templates, config files)
- CONTENT_FIX: Can be fixed via CMS API (Drupal content, media)
- MANUAL_ONLY: Requires human judgment (design decisions, legal)
- NOT_FIXABLE: Detection-only (3rd party, external resources)
"""

import re
from typing import Optional

from ..models import Issue, FixType


class FixClassifier:
    """Classifies issues into fix types based on category and content."""

    # Mapping of (category, title_pattern) to fix types
    # Use "*" as title pattern to match all issues in a category
    CLASSIFICATION_RULES: list[tuple[str, str, FixType]] = [
        # CONTENT_FIX: Issues fixable via Drupal API
        ("accessibility", "Image missing alt text", FixType.CONTENT_FIX),
        ("accessibility", "Missing alt text", FixType.CONTENT_FIX),
        ("spelling", "*", FixType.CONTENT_FIX),
        ("grammar", "*", FixType.CONTENT_FIX),
        ("seo", "Missing meta description", FixType.CONTENT_FIX),
        ("seo", "Meta description too short", FixType.CONTENT_FIX),
        ("seo", "Meta description too long", FixType.CONTENT_FIX),

        # CODE_FIX: Issues fixable via Git PR
        ("accessibility", "Missing language declaration", FixType.CODE_FIX),
        ("accessibility", "Empty link text", FixType.CODE_FIX),
        ("accessibility", "Link has no text", FixType.CODE_FIX),
        ("accessibility", "Icon button missing accessible name", FixType.CODE_FIX),
        ("accessibility", "Missing form label", FixType.CODE_FIX),
        ("seo", "Missing canonical", FixType.CODE_FIX),
        ("seo", "Missing canonical URL", FixType.CODE_FIX),
        ("seo", "Multiple H1 tags", FixType.CODE_FIX),
        ("mobile", "Viewport not configured", FixType.CODE_FIX),
        ("mobile", "Missing viewport meta tag", FixType.CODE_FIX),

        # MANUAL_ONLY: Requires human decision
        ("compliance", "No cookie consent", FixType.MANUAL_ONLY),
        ("compliance", "Cookie consent", FixType.MANUAL_ONLY),
        ("compliance", "Third-party tracking", FixType.MANUAL_ONLY),
        ("compliance", "Missing privacy policy", FixType.MANUAL_ONLY),
        ("security", "*", FixType.MANUAL_ONLY),
        ("performance", "*", FixType.MANUAL_ONLY),

        # NOT_FIXABLE: External resources
        ("links", "External broken link", FixType.NOT_FIXABLE),
        ("links", "External link returns", FixType.NOT_FIXABLE),
    ]

    # Default fix types by category (used when no specific rule matches)
    CATEGORY_DEFAULTS: dict[str, FixType] = {
        "spelling": FixType.CONTENT_FIX,
        "grammar": FixType.CONTENT_FIX,
        "formatting": FixType.CONTENT_FIX,
        "accessibility": FixType.CODE_FIX,
        "seo": FixType.CODE_FIX,
        "mobile": FixType.CODE_FIX,
        "links": FixType.MANUAL_ONLY,
        "compliance": FixType.MANUAL_ONLY,
        "security": FixType.MANUAL_ONLY,
        "performance": FixType.MANUAL_ONLY,
    }

    def classify(self, issue: Issue) -> FixType:
        """Classify an issue into a fix type.

        Args:
            issue: The issue to classify

        Returns:
            The appropriate FixType for this issue
        """
        category = issue.category.lower() if isinstance(issue.category, str) else issue.category.value.lower()
        title = issue.title.lower()

        # Check specific rules first (in order)
        for rule_category, rule_pattern, fix_type in self.CLASSIFICATION_RULES:
            if category != rule_category.lower():
                continue

            if rule_pattern == "*":
                return fix_type

            if rule_pattern.lower() in title:
                return fix_type

        # Fall back to category default
        return self.CATEGORY_DEFAULTS.get(category, FixType.NOT_FIXABLE)

    def get_confidence(self, issue: Issue, fix_type: Optional[FixType] = None) -> float:
        """Estimate confidence in the fix based on issue details.

        Args:
            issue: The issue to assess
            fix_type: The fix type (if already classified)

        Returns:
            Confidence score from 0.0 to 1.0
        """
        if fix_type is None:
            fix_type = self.classify(issue)

        title = issue.title.lower()
        description = (issue.description or "").lower()

        # NOT_FIXABLE and MANUAL_ONLY have no auto-fix confidence
        if fix_type in (FixType.NOT_FIXABLE, FixType.MANUAL_ONLY):
            return 0.0

        # CONTENT_FIX confidence
        if fix_type == FixType.CONTENT_FIX:
            # Spelling errors with specific suggestions are high confidence
            if "spelling" in title or issue.category == "spelling":
                if "→" in description or "should be" in description:
                    return 0.95
                return 0.7

            # Grammar with suggestions
            if "grammar" in title or issue.category == "grammar":
                if "→" in description or "suggested" in description:
                    return 0.85
                return 0.65

            # Alt text - AI can generate, medium-high confidence
            if "alt text" in title or "alt attribute" in title:
                return 0.80

            # Meta descriptions - AI can generate, medium confidence
            if "meta description" in title:
                return 0.70

            return 0.6

        # CODE_FIX confidence
        if fix_type == FixType.CODE_FIX:
            # Lang attribute is a simple, high-confidence fix
            if "lang" in title or "language declaration" in title:
                return 0.95

            # Empty link text - straightforward template fix
            if "empty link" in title or "link has no text" in title:
                return 0.85

            # Form labels - may need context
            if "label" in title:
                return 0.75

            # Multiple H1s - need to determine which to change
            if "h1" in title:
                return 0.70

            # Canonical URLs - depends on site structure
            if "canonical" in title:
                return 0.80

            return 0.7

        return 0.5

    def get_fix_description(self, issue: Issue) -> str:
        """Get a description of how to fix this issue.

        Args:
            issue: The issue to describe

        Returns:
            Human-readable description of the fix approach
        """
        fix_type = self.classify(issue)
        title = issue.title.lower()

        if fix_type == FixType.NOT_FIXABLE:
            return "This issue cannot be automatically fixed (external resource or third-party)."

        if fix_type == FixType.MANUAL_ONLY:
            return "This issue requires manual review and decision-making."

        if fix_type == FixType.CONTENT_FIX:
            if "alt text" in title:
                return "AI will generate descriptive alt text and create a Drupal draft revision."
            if "spelling" in title or issue.category == "spelling":
                return "The spelling correction will be applied to the Drupal content as a draft."
            if "grammar" in title or issue.category == "grammar":
                return "The grammar correction will be applied to the Drupal content as a draft."
            if "meta description" in title:
                return "AI will generate a meta description and update the Drupal node as a draft."
            return "This content will be updated in Drupal as a draft revision for review."

        if fix_type == FixType.CODE_FIX:
            if "lang" in title:
                return "A PR will be created to add lang='en' to the html element in html.html.twig."
            if "link" in title:
                return "A PR will be created to add aria-label or visible text to the link."
            if "h1" in title:
                return "A PR will be created to fix the heading structure in the template."
            if "canonical" in title:
                return "A PR will be created to add canonical URL configuration."
            return "A GitHub PR will be created with the template fix."

        return "Fix approach not determined."

    def is_fixable(self, issue: Issue) -> bool:
        """Check if an issue can be automatically fixed.

        Args:
            issue: The issue to check

        Returns:
            True if the issue can be fixed (CODE_FIX or CONTENT_FIX)
        """
        fix_type = self.classify(issue)
        return fix_type in (FixType.CODE_FIX, FixType.CONTENT_FIX)
