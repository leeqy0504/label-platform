from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from label_platform.api.routes.datasets import router as datasets_router
from label_platform.api.routes.jobs import router as jobs_router
from label_platform.api.routes.roots import router as roots_router
from label_platform.api.routes.system import router as system_router
from label_platform.api.routes.reviews import integration_router, router as reviews_router
from label_platform.api.routes.training import (
    integration_router as unitrain_integration_router,
    models_router,
    router as training_router,
)
from label_platform.config import Settings
from label_platform.db.session import create_engine_from_settings, create_session_factory
from label_platform.jobs.queue import RQJobQueue
from label_platform.integrations.labelstudio import create_label_studio_connector
from label_platform.integrations.unitrain import create_unitrain_connector


def create_app(settings: Settings) -> FastAPI:
    label_studio_connector = create_label_studio_connector(settings)
    unitrain_connector = create_unitrain_connector(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.managed_data_root.mkdir(parents=True, exist_ok=True)
        settings.label_studio_export_root.mkdir(parents=True, exist_ok=True)
        settings.unitrain_export_root.mkdir(parents=True, exist_ok=True)
        engine = create_engine_from_settings(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()
            label_studio_connector.close()
            unitrain_connector.close()

    app = FastAPI(title="Label Platform API", lifespan=lifespan)
    app.state.settings = settings
    app.state.job_queue = RQJobQueue(settings.redis_url)
    app.state.label_studio_connector = label_studio_connector
    app.state.unitrain_connector = unitrain_connector
    app.include_router(datasets_router)
    app.include_router(jobs_router)
    app.include_router(roots_router)
    app.include_router(reviews_router)
    app.include_router(integration_router)
    app.include_router(training_router)
    app.include_router(models_router)
    app.include_router(unitrain_integration_router)
    app.include_router(system_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "label-platform-api"}

    return app


def create_app_from_env() -> FastAPI:
    return create_app(Settings())
