"""Base analyzer interface.

All analyzers inherit from this base class to ensure consistent interface.
"""

from abc import ABC, abstractmethod
from typing import Optional

from bs4 import BeautifulSoup

from ..models import Issue, IssueCategory


class BaseAnalyzer(ABC):
    """Base class for all analyzers.

    Each analyzer is responsible for checking a specific category of issues
    and returning a list of Issue objects.
    """

    category: IssueCategory

    @abstractmethod
    def analyze(
        self,
        url: str,
        html: str,
        text: str,
        soup: Optional[BeautifulSoup] = None,
    ) -> list[Issue]:
        """Analyze a page and return found issues.

        Args:
            url: The URL of the page
            html: Raw HTML content
            text: Extracted visible text
            soup: Optional pre-parsed BeautifulSoup object

        Returns:
            List of Issue objects found on this page
        """
        pass

    def _get_soup(self, html: str, soup: Optional[BeautifulSoup] = None) -> BeautifulSoup:
        """Get or create BeautifulSoup object."""
        if soup is not None:
            return soup
        return BeautifulSoup(html, "lxml")

    def _create_issue(
        self,
        severity: str,
        title: str,
        description: str,
        recommendation: str,
        url: str,
        element: Optional[str] = None,
        context: Optional[str] = None,
        line_number: Optional[int] = None,
    ) -> Issue:
        """Helper to create an Issue with this analyzer's category."""
        return Issue(
            category=self.category,
            severity=severity,
            title=title,
            description=description,
            recommendation=recommendation,
            url=url,
            element=element,
            context=context,
            line_number=line_number,
        )
