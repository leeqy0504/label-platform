from datetime import datetime
import re
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from label_platform.api.dependencies import CurrentUser, SessionDependency, require_roles
from label_platform.db.models import (
    BackgroundJob,
    TrainingRun,
    User,
)
from label_platform.domain.enums import JobStatus, TaskType, TrainingStatus, UserRole
from label_platform.integrations.unitrain import (
    UnitTrainConnector,
    UnitTrainConnectorError,
    UnitTrainMetrics,
    UnitTrainModel,
    UnitTrainUnavailableError,
)
from label_platform.jobs.queue import JobQueue
from label_platform.training.service import (
    TrainingConflictError,
    TrainingWorkflow,
    TrainingWorkflowError,
)


router = APIRouter(prefix="/api/training-runs", tags=["training"])
models_router = APIRouter(prefix="/api/models", tags=["models"])
integration_router = APIRouter(prefix="/api/integrations/unitrain", tags=["integrations"])
TrainingOperator = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
]


class TrainingConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    framework: Literal["ultralytics", "yolo", "rfdetr", "rf-detr"] = "ultralytics"
    model: str = Field(min_length=1, max_length=120)
    epochs: int = Field(
        default=100,
        ge=1,
        le=10_000,
        validation_alias=AliasChoices("epochs", "totalEpochs"),
    )
    batch_size: int = Field(
        default=16,
        ge=1,
        le=4_096,
        validation_alias=AliasChoices("batch_size", "batchSize"),
    )
    learning_rate: float = Field(default=1e-4, gt=0, le=1)
    image_size: int = Field(default=640, ge=32, le=8_192)
    device: int | str = 0
    grad_accum_steps: int = Field(default=4, ge=1, le=1_024)
    early_stopping: bool = False
    early_stopping_patience: int = Field(default=10, ge=1, le=10_000)
    early_stopping_min_delta: float = Field(default=0.001, ge=0, le=1)
    skip_evaluation: bool = False

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError("model must be a plain model name")
        return value

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: int | str) -> int | str:
        if isinstance(value, int):
            if value < 0:
                raise ValueError("device must be non-negative")
            return value
        normalized = value.strip().lower()
        if normalized == "cpu" or re.fullmatch(r"(?:cuda:)?\d+(?:,\d+)*", normalized):
            return normalized
        raise ValueError("device must be cpu, a GPU index, or a comma-separated GPU list")


class CreateTrainingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    dataset_id: str
    dataset_version_id: str
    config: TrainingConfigRequest
    idempotency_key: str = Field(min_length=1, max_length=180)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class TrainingResponse(BaseModel):
    id: str
    name: str
    dataset_id: str
    dataset_name: str
    dataset_version_id: str
    dataset_version_number: int
    task_type: TaskType
    status: TrainingStatus
    unitrain_run_id: str | None
    current_epoch: int
    total_epochs: int
    metric_summary: dict[str, float]
    config: dict[str, Any]
    external_detail_url: str | None
    export_profile: str
    error_summary: dict[str, Any]
    created_by: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    job_id: str | None


class TrainingLogsResponse(BaseModel):
    run_id: str
    offset: int
    next_offset: int
    lines: list[str]
    truncated: bool


class TrainingMetricsResponse(BaseModel):
    run_id: str
    summary: dict[str, float]
    history: list[dict[str, Any]]
    evaluation: dict[str, Any]


class ModelResponse(BaseModel):
    id: str
    name: str
    training_run_id: str
    unitrain_run_id: str
    dataset_id: str
    dataset_name: str
    dataset_version_id: str
    dataset_version_number: int
    task_type: TaskType
    framework: str
    metrics: dict[str, float]
    category_metrics: list[dict[str, Any]]
    categories: list[str]
    file_size: int
    file_path: str
    evaluation_files: list[str]
    evaluation_links: list[dict[str, str]]
    created_at: datetime
    created_by: str


def _workflow(request: Request) -> TrainingWorkflow:
    settings = request.app.state.settings
    return TrainingWorkflow(
        request.app.state.session_factory,
        managed_root=settings.managed_data_root,
        export_root=settings.unitrain_export_root,
        unitrain_mount_root=settings.unitrain_mount_root,
        connector=cast(UnitTrainConnector, request.app.state.unitrain_connector),
    )


@router.post("", response_model=TrainingResponse, status_code=status.HTTP_202_ACCEPTED)
def create_training_run(
    payload: CreateTrainingRequest,
    request: Request,
    session: SessionDependency,
    operator: TrainingOperator,
) -> TrainingResponse:
    config = payload.config.model_dump()
    try:
        run = _workflow(request).create_run(
            dataset_id=payload.dataset_id,
            dataset_version_id=payload.dataset_version_id,
            name=payload.name,
            config=config,
            created_by_id=operator.id,
            idempotency_key=f"{operator.id}:{payload.idempotency_key}",
        )
    except TrainingConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except TrainingWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    session.expire_all()
    job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.business_object_id == run.id,
            BackgroundJob.job_type == "training_submission",
        )
    )
    if job is None:
        job = BackgroundJob(
            business_object_id=run.id,
            job_type="training_submission",
            idempotency_key=f"training-submission:{run.id}",
            status=JobStatus.PENDING,
            stage="pending",
            result={"request": {"training_run_id": run.id}},
            created_by_id=operator.id,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        try:
            cast(JobQueue, request.app.state.job_queue).enqueue_training_submission(job.id)
        except Exception as exc:
            _queue_failed(session, job, exc)
            _workflow(request).fail_submission(run.id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Training submission could not be queued",
            ) from exc
    session.expire_all()
    return _response(_require_run(session, run.id), job_id=job.id)


@router.get("")
def list_training_runs(
    session: SessionDependency,
    _: CurrentUser,
    dataset_id: str | None = None,
    status_filter: TrainingStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    query = select(TrainingRun)
    count_query = select(func.count()).select_from(TrainingRun)
    if dataset_id is not None:
        query = query.where(TrainingRun.dataset_id == dataset_id)
        count_query = count_query.where(TrainingRun.dataset_id == dataset_id)
    if status_filter is not None:
        query = query.where(TrainingRun.status == status_filter)
        count_query = count_query.where(TrainingRun.status == status_filter)
    if search is not None and (term := search.strip()):
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        predicate = TrainingRun.name.ilike(f"%{escaped}%", escape="\\")
        query = query.where(predicate)
        count_query = count_query.where(predicate)
    total = session.scalar(count_query) or 0
    runs = session.scalars(
        query
        .order_by(TrainingRun.created_at.desc(), TrainingRun.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [
            _response(run, job_id=_latest_job_id(session, run.id)).model_dump()
            for run in runs
        ],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


@router.get("/{run_id}", response_model=TrainingResponse)
def get_training_run(
    run_id: str,
    session: SessionDependency,
    _: CurrentUser,
) -> TrainingResponse:
    return _response(_require_run(session, run_id), job_id=_latest_job_id(session, run_id))


@router.post("/{run_id}/sync", response_model=TrainingResponse)
def sync_training_run(
    run_id: str,
    request: Request,
    session: SessionDependency,
    _: CurrentUser,
) -> TrainingResponse:
    _require_run(session, run_id)
    try:
        _workflow(request).reconcile(run_id)
    except TrainingWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnitTrainConnectorError as exc:
        raise _connector_http_error(exc) from exc
    session.expire_all()
    return _response(_require_run(session, run_id), job_id=_latest_job_id(session, run_id))


@router.get("/{run_id}/logs", response_model=TrainingLogsResponse)
def get_training_logs(
    run_id: str,
    request: Request,
    session: SessionDependency,
    _: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> TrainingLogsResponse:
    _require_run(session, run_id)
    try:
        logs = _workflow(request).logs(run_id, offset=offset, limit=limit)
    except TrainingWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnitTrainConnectorError as exc:
        raise _connector_http_error(exc) from exc
    return TrainingLogsResponse(
        run_id=run_id,
        offset=logs.offset,
        next_offset=logs.next_offset,
        lines=logs.lines,
        truncated=logs.truncated,
    )


@router.get("/{run_id}/metrics", response_model=TrainingMetricsResponse)
def get_training_metrics(
    run_id: str,
    request: Request,
    session: SessionDependency,
    _: CurrentUser,
) -> TrainingMetricsResponse:
    _require_run(session, run_id)
    try:
        metrics = _workflow(request).metrics(run_id)
    except TrainingWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnitTrainConnectorError as exc:
        raise _connector_http_error(exc) from exc
    return _metrics_response(run_id, metrics)


@router.post("/{run_id}/stop", response_model=TrainingResponse)
def stop_training_run(
    run_id: str,
    request: Request,
    session: SessionDependency,
    _: TrainingOperator,
) -> TrainingResponse:
    _require_run(session, run_id)
    try:
        _workflow(request).stop(run_id)
    except TrainingWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnitTrainConnectorError as exc:
        raise _connector_http_error(exc) from exc
    session.expire_all()
    return _response(_require_run(session, run_id), job_id=_latest_job_id(session, run_id))


@models_router.get("")
def list_models(
    request: Request,
    session: SessionDependency,
    _: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    task_type: TaskType | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    try:
        remote_models = _all_remote_models(
            cast(UnitTrainConnector, request.app.state.unitrain_connector)
        )
    except UnitTrainConnectorError as exc:
        raise _connector_http_error(exc) from exc
    mapped = _map_models(session, remote_models)
    if search is not None and (term := search.strip().casefold()):
        mapped = [model for model in mapped if term in model.name.casefold()]
    if task_type is not None:
        mapped = [model for model in mapped if model.task_type is task_type]
    start = (page - 1) * page_size
    return {
        "data": [model.model_dump() for model in mapped[start : start + page_size]],
        "meta": {"page": page, "page_size": page_size, "total": len(mapped)},
    }


@models_router.get("/{model_id}", response_model=ModelResponse)
def get_model(
    model_id: str,
    request: Request,
    session: SessionDependency,
    _: CurrentUser,
) -> ModelResponse:
    connector = cast(UnitTrainConnector, request.app.state.unitrain_connector)
    try:
        remote = connector.get_model(model_id)
        metrics = connector.get_metrics(remote.run_id)
    except UnitTrainConnectorError as exc:
        raise _connector_http_error(exc) from exc
    mapped = _map_models(session, [remote], metrics_by_run={remote.run_id: metrics})
    if not mapped:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    return mapped[0]


@models_router.get("/{model_id}/artifacts/{artifact_index}")
def get_model_artifact(
    model_id: str,
    artifact_index: int,
    request: Request,
    session: SessionDependency,
    _: CurrentUser,
) -> Response:
    connector = cast(UnitTrainConnector, request.app.state.unitrain_connector)
    try:
        remote = connector.get_model(model_id)
    except UnitTrainConnectorError as exc:
        raise _connector_http_error(exc) from exc
    if not _map_models(session, [remote]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    if artifact_index < 0 or artifact_index >= len(remote.evaluation_files):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    try:
        artifact = connector.get_model_artifact(
            model_id,
            remote.evaluation_files[artifact_index],
        )
    except UnitTrainConnectorError as exc:
        raise _connector_http_error(exc) from exc
    filename = artifact.filename.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content=artifact.content,
        media_type=artifact.content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@integration_router.get("/health")
def unitrain_health(request: Request, _: CurrentUser) -> dict[str, str]:
    connector = cast(UnitTrainConnector, request.app.state.unitrain_connector)
    try:
        return {"status": "online", "version": connector.health()}
    except Exception:
        return {"status": "offline", "version": ""}


def _response(run: TrainingRun, *, job_id: str | None) -> TrainingResponse:
    return TrainingResponse(
        id=run.id,
        name=run.name,
        dataset_id=run.dataset_id,
        dataset_name=run.dataset.name,
        dataset_version_id=run.dataset_version_id,
        dataset_version_number=run.dataset_version.version_number,
        task_type=run.task_type,
        status=run.status,
        unitrain_run_id=run.unitrain_run_id,
        current_epoch=run.current_epoch,
        total_epochs=run.total_epochs,
        metric_summary=run.metric_summary,
        config=run.config,
        external_detail_url=run.external_detail_url,
        export_profile=run.export_profile,
        error_summary=run.error_summary,
        created_by=run.created_by.name,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        job_id=job_id,
    )


def _metrics_response(run_id: str, metrics: UnitTrainMetrics) -> TrainingMetricsResponse:
    return TrainingMetricsResponse(
        run_id=run_id,
        summary=metrics.summary,
        history=metrics.history,
        evaluation=metrics.evaluation,
    )


def _all_remote_models(connector: UnitTrainConnector) -> list[UnitTrainModel]:
    models: list[UnitTrainModel] = []
    page = 1
    while True:
        batch, total = connector.list_models(page=page, page_size=500)
        models.extend(batch)
        if len(models) >= total or not batch:
            return models
        page += 1


def _map_models(
    session: SessionDependency,
    models: list[UnitTrainModel],
    *,
    metrics_by_run: dict[str, UnitTrainMetrics] | None = None,
) -> list[ModelResponse]:
    run_ids = {model.run_id for model in models}
    runs = session.scalars(
        select(TrainingRun).where(TrainingRun.unitrain_run_id.in_(run_ids))
    ).all() if run_ids else []
    by_external_id = {run.unitrain_run_id: run for run in runs}
    responses: list[ModelResponse] = []
    for model in models:
        run = by_external_id.get(model.run_id)
        if run is None:
            continue
        schema = run.dataset_version.class_schema
        categories = [
            str(category["name"])
            for category in schema
            if isinstance(category, dict) and isinstance(category.get("name"), str)
        ]
        metrics = (metrics_by_run or {}).get(model.run_id)
        category_metrics: list[dict[str, Any]] = []
        if metrics is not None:
            raw = metrics.evaluation.get("per_class")
            if isinstance(raw, list):
                category_metrics = [item for item in raw if isinstance(item, dict)]
        responses.append(
            ModelResponse(
                id=model.id,
                name=model.name,
                training_run_id=run.id,
                unitrain_run_id=model.run_id,
                dataset_id=run.dataset_id,
                dataset_name=run.dataset.name,
                dataset_version_id=run.dataset_version_id,
                dataset_version_number=run.dataset_version.version_number,
                task_type=run.task_type,
                framework=model.framework,
                metrics=model.metrics,
                category_metrics=category_metrics,
                categories=categories,
                file_size=model.size_bytes,
                file_path=model.relative_path,
                evaluation_files=model.evaluation_files,
                evaluation_links=[
                    {
                        "name": path,
                        "url": f"/api/models/{model.id}/artifacts/{index}",
                    }
                    for index, path in enumerate(model.evaluation_files)
                ],
                created_at=model.created_at,
                created_by=run.created_by.name,
            )
        )
    return responses


def _require_run(session: SessionDependency, run_id: str) -> TrainingRun:
    run = session.get(TrainingRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training run not found")
    return run


def _latest_job_id(session: SessionDependency, run_id: str) -> str | None:
    return session.scalar(
        select(BackgroundJob.id)
        .where(BackgroundJob.business_object_id == run_id)
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )


def _queue_failed(session: SessionDependency, job: BackgroundJob, error: Exception) -> None:
    session.rollback()
    stored = session.get(BackgroundJob, job.id)
    if stored is None:
        return
    stored.status = JobStatus.FAILED
    stored.stage = "queue_failed"
    stored.error_summary = {"code": "queue_unavailable", "message": str(error)}
    session.commit()


def _connector_http_error(error: UnitTrainConnectorError) -> HTTPException:
    code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if isinstance(error, UnitTrainUnavailableError)
        else status.HTTP_502_BAD_GATEWAY
    )
    return HTTPException(status_code=code, detail=str(error))
