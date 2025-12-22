"""Crawler modules for Website Quality Agent."""

from .playwright_crawler import PlaywrightCrawler
from .simple_crawler import SimpleCrawler

__all__ = ["PlaywrightCrawler", "SimpleCrawler"]
