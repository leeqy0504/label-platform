from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse

from unitrain_api.config import UnitTrainAPISettings
from unitrain_api.schemas import (
    CreateRunRequest,
    ModelRecord,
    PositiveLimit,
    RunLogs,
    RunMetrics,
    RunRecord,
)
from unitrain_api.service import RunConflictError, RunManager
from unitrain_api.store import ModelNotFoundError, RunNotFoundError


def create_app(
    settings: UnitTrainAPISettings,
    *,
    manager: RunManager | None = None,
) -> FastAPI:
    run_manager = manager or RunManager(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.run_root.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title="UniTrain API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.run_manager = run_manager

    def authorize(
        authorization: Annotated[str | None, Header()] = None,
        x_api_key: Annotated[str | None, Header()] = None,
    ) -> None:
        if not settings.api_token:
            return
        bearer = authorization.removeprefix("Bearer ") if authorization else None
        bearer_matches = bearer is not None and secrets.compare_digest(
            bearer,
            settings.api_token,
        )
        key_matches = x_api_key is not None and secrets.compare_digest(
            x_api_key,
            settings.api_token,
        )
        if not bearer_matches and not key_matches:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")

    Auth = Annotated[None, Depends(authorize)]

    @app.get("/health")
    def health(_: Auth) -> dict[str, str]:
        return {"status": "online", "service": "unitrain-api", "version": "1.0.0"}

    @app.post("/runs", response_model=RunRecord, status_code=status.HTTP_202_ACCEPTED)
    def create_run(payload: CreateRunRequest, _: Auth) -> RunRecord:
        try:
            return run_manager.create_run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except RunConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.get("/runs")
    def list_runs(
        _: Auth,
        page: int = Query(default=1, ge=1),
        page_size: PositiveLimit = 20,
    ) -> dict[str, object]:
        runs = run_manager.list_runs()
        start = (page - 1) * page_size
        return {
            "data": [run.model_dump(mode="json") for run in runs[start : start + page_size]],
            "meta": {"page": page, "page_size": page_size, "total": len(runs)},
        }

    @app.get("/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: str, _: Auth) -> RunRecord:
        try:
            return run_manager.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc

    @app.get("/runs/{run_id}/logs", response_model=RunLogs)
    def get_logs(
        run_id: str,
        _: Auth,
        offset: int = Query(default=0, ge=0),
        limit: PositiveLimit = 200,
    ) -> RunLogs:
        try:
            return run_manager.store.read_logs(run_id, offset=offset, limit=limit)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc

    @app.get("/runs/{run_id}/metrics", response_model=RunMetrics)
    def get_metrics(run_id: str, _: Auth) -> RunMetrics:
        try:
            return run_manager.store.read_metrics(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc

    @app.post("/runs/{run_id}/stop", response_model=RunRecord)
    def stop_run(run_id: str, _: Auth) -> RunRecord:
        try:
            return run_manager.stop_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc
        except RunConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.get("/models")
    def list_models(
        _: Auth,
        page: int = Query(default=1, ge=1),
        page_size: PositiveLimit = 20,
    ) -> dict[str, object]:
        models = run_manager.store.list_models()
        start = (page - 1) * page_size
        return {
            "data": [model.model_dump(mode="json") for model in models[start : start + page_size]],
            "meta": {"page": page, "page_size": page_size, "total": len(models)},
        }

    @app.get("/models/{model_id}", response_model=ModelRecord)
    def get_model(model_id: str, _: Auth) -> ModelRecord:
        try:
            return run_manager.store.get_model(model_id)
        except ModelNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found") from exc

    @app.get("/models/{model_id}/artifacts/{artifact_path:path}")
    def get_model_artifact(model_id: str, artifact_path: str, _: Auth) -> FileResponse:
        try:
            artifact = run_manager.store.get_model_artifact(model_id, artifact_path)
        except (ModelNotFoundError, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Model artifact not found",
            ) from exc
        return FileResponse(artifact, filename=artifact.name)

    return app


def create_app_from_env() -> FastAPI:
    return create_app(UnitTrainAPISettings())
