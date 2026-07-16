import uvicorn

from unitrain_api.config import UnitTrainAPISettings


def main() -> None:
    settings = UnitTrainAPISettings()
    uvicorn.run(
        "unitrain_api.app:create_app_from_env",
        factory=True,
        host=settings.host,
        port=settings.port,
    )
