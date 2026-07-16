from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from label_platform.config import Settings


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.managed_data_root.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title="Label Platform API", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "label-platform-api"}

    return app
