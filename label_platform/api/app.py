from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from label_platform.api.dependencies import require_roles
from label_platform.api.routes.auth import router as auth_router
from label_platform.api.routes.roots import router as roots_router
from label_platform.api.routes.users import router as users_router
from label_platform.config import Settings
from label_platform.db.session import create_engine_from_settings, create_session_factory
from label_platform.domain.enums import UserRole


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.managed_data_root.mkdir(parents=True, exist_ok=True)
        engine = create_engine_from_settings(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Label Platform API", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(auth_router)
    app.include_router(roots_router)
    app.include_router(users_router)

    if settings.environment == "test":

        @app.get("/api/auth/admin-probe")
        def admin_probe(_: object = Depends(require_roles(UserRole.ADMIN))) -> dict[str, bool]:
            return {"admin": True}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "label-platform-api"}

    return app
