from functools import lru_cache
from typing import Optional

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    database_path: str = Field(default="data/agent.db", alias="AGENT_DATABASE_PATH")
    rate_limit_seconds: float = Field(default=1.5, alias="AGENT_RATE_LIMIT_SECONDS")
    default_max_pages: int = Field(default=25, alias="AGENT_DEFAULT_MAX_PAGES")
    base_url: Optional[HttpUrl] = Field(default=None, alias="AGENT_BASE_URL")
    timezone: str = Field(default="America/Los_Angeles", alias="AGENT_TIMEZONE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

