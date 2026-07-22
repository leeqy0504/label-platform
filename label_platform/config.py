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
    environment: Literal["development", "test", "production"] = "development"
    label_studio_url: str = "http://127.0.0.1:8081"
    label_studio_public_url: str = "http://127.0.0.1:8081"
    label_studio_api_token: str = ""
    label_studio_mount_root: Path = Path("/datasets")
    label_studio_export_root: Path = Path("./var/labelstudio/exports")
    label_studio_timeout_seconds: float = Field(default=120, gt=0, le=600)
    unitrain_url: str = "http://127.0.0.1:8090"
    unitrain_api_token: str = ""
    unitrain_export_root: Path = Path("./var/unitrain/exports")
    unitrain_mount_root: Path = Path("./var/unitrain/exports")
    unitrain_timeout_seconds: float = Field(default=120, gt=0, le=600)
