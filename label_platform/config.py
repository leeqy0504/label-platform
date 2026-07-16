from pathlib import Path

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
    session_secret: str
    session_max_age_seconds: int = 28_800
    secure_cookies: bool = False
