"""Configuration management for Website Quality Agent.

Loads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# OpenAI configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Crawler configuration
CRAWLER_DELAY = float(os.getenv("CRAWLER_DELAY", "3.0"))
CRAWLER_MAX_PAGES = int(os.getenv("CRAWLER_MAX_PAGES", "100"))
CRAWLER_TIMEOUT = int(os.getenv("CRAWLER_TIMEOUT", "30"))
CRAWLER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Storage
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "website_agent.db")))

# API configuration
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8002"))

# Lighthouse configuration
LIGHTHOUSE_PATH = os.getenv("LIGHTHOUSE_PATH", "lighthouse")

# Severity weights for scoring
SEVERITY_WEIGHTS = {
    "critical": 10,
    "high": 5,
    "medium": 2,
    "low": 1,
}

# Issue categories
ISSUE_CATEGORIES = [
    "seo",
    "spelling",
    "grammar",
    "formatting",
    "accessibility",
    "links",
    "compliance",
    "performance",
    "mobile",
    "security",
]


def ensure_data_dir():
    """Ensure the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
