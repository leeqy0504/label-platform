from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class UnitTrainAPISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="UNITRAIN_API_",
        env_file=".env",
        extra="ignore",
    )

    run_root: Path = Path("./var/unitrain/runs")
    api_token: str = ""
    public_url: str = "http://127.0.0.1:8090"
    host: str = "127.0.0.1"
    port: int = Field(default=8090, ge=1, le=65_535)
    max_concurrent_runs: int = Field(default=1, ge=1, le=32)
    stop_timeout_seconds: float = Field(default=10, gt=0, le=120)
