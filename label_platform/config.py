from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PLATFORM_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://platform:platform@localhost:5432/platform"
    redis_url: str = "redis://localhost:6379/0"
    managed_data_root: Path = Path("./var/managed")
    session_secret: str = Field(min_length=32)
    session_max_age_seconds: int = 28_800
    secure_cookies: bool = False
    environment: Literal["development", "test", "production"] = "development"
