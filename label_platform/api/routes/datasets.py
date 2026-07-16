from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from label_platform.api.dependencies import CurrentUser, SessionDependency, require_roles
from label_platform.datasets.paths import SourcePathError, resolve_source_path
from label_platform.db.models import (
    AllowedRoot,
    AuditEvent,
    BackgroundJob,
    Dataset,
    DatasetItem,
    DatasetSource,
    DatasetVersion,
    TrainingRun,
    User,
)
from label_platform.domain.enums import JobStatus, SourceFormat, TaskType, UserRole, VersionStatus
from label_platform.jobs.queue import JobQueue


router = APIRouter(prefix="/api/datasets", tags=["datasets"])
DatasetOperator = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
]


class SplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train: float = Field(ge=0, le=1)
    val: float = Field(ge=0, le=1)
    test: float = Field(ge=0, le=1)
    seed: int = 42

    @model_validator(mode="after")
    def ratios_sum_to_one(self) -> "SplitRequest":
        if abs(self.train + self.val + self.test - 1.0) > 1e-9:
            raise ValueError("Split ratios must sum to one")
        return self


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_root_id: str
    relative_path: str = ""
    categories: list[str] = Field(default_factory=list)
    task_type: TaskType = TaskType.DETECTION
    split: SplitRequest
    idempotency_key: str = Field(min_length=1, max_length=180)

    @field_validator("categories")
    @classmethod
    def normalize_categories(cls, value: list[str]) -> list[str]:
        normalized = [category.strip() for category in value]
        if any(not category for category in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("Categories must contain unique non-empty names")
        return normalized


class DatasetAnalyzeRequest(SourceSelection):
    pass


class DatasetRegisterRequest(SourceSelection):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    analysis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class JobAccepted(BaseModel):
    job_id: str
    status: JobStatus


def _queue(request: Request) -> JobQueue:
    return cast(JobQueue, request.app.state.job_queue)


def _active_root(session: SessionDependency, root_id: str) -> AllowedRoot:
    root = session.get(AllowedRoot, root_id)
    if root is None or not root.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source root not found")
    return root


def _resolve_selection(root: AllowedRoot, relative_path: str) -> Path:
    try:
        return resolve_source_path(Path(root.path), relative_path)
    except SourcePathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _selection_request(
    payload: SourceSelection,
    source_path: Path,
) -> dict[str, object]:
    return {
        "source_root_id": payload.source_root_id,
        "relative_path": payload.relative_path,
        "source_path": str(source_path),
        "categories": payload.categories,
        "task_type": payload.task_type.value,
        "split": payload.split.model_dump(),
    }


def _idempotent_job(
    session: SessionDependency,
    *,
    key: str,
    request_payload: dict[str, object],
) -> BackgroundJob | None:
    job = session.scalar(select(BackgroundJob).where(BackgroundJob.idempotency_key == key))
    if job is None:
        return None
    stored_request = job.result.get("request")
    if not isinstance(stored_request, dict) or any(
        stored_request.get(key) != value for key, value in request_payload.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used with a different request",
        )
    return job


@router.post("/analyze", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def analyze_dataset(
    payload: DatasetAnalyzeRequest,
    request: Request,
    session: SessionDependency,
    operator: DatasetOperator,
) -> JobAccepted:
    root = _active_root(session, payload.source_root_id)
    source_path = _resolve_selection(root, payload.relative_path)
    request_payload = _selection_request(payload, source_path)
    key = f"analysis:{operator.id}:{payload.idempotency_key}"
    existing = _idempotent_job(session, key=key, request_payload=request_payload)
    if existing is not None:
        return JobAccepted(job_id=existing.id, status=existing.status)

    job = BackgroundJob(
        job_type="dataset_analysis",
        idempotency_key=key,
        status=JobStatus.PENDING,
        stage="pending",
        result={"request": request_payload},
        created_by_id=operator.id,
    )
    session.add(job)
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=operator.id,
            action="dataset.analysis_requested",
            resource_type="background_job",
            resource_id=job.id,
            details={"source_root_id": root.id, "relative_path": payload.relative_path},
            ip_address=request.client.host if request.client else None,
        )
    )
    session.commit()
    try:
        _queue(request).enqueue_analysis(job.id)
    except Exception as exc:
        _mark_enqueue_failed(session, job.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset analysis could not be queued",
        ) from exc
    return JobAccepted(job_id=job.id, status=JobStatus.PENDING)


@router.post("/register", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def register_dataset(
    payload: DatasetRegisterRequest,
    request: Request,
    session: SessionDependency,
    operator: DatasetOperator,
) -> JobAccepted:
    root = _active_root(session, payload.source_root_id)
    source_path = _resolve_selection(root, payload.relative_path)
    selection = _selection_request(payload, source_path)
    request_payload = {
        **selection,
        "name": payload.name,
        "description": payload.description,
        "analysis_fingerprint": payload.analysis_fingerprint,
    }
    key = f"registration:{operator.id}:{payload.idempotency_key}"
    existing = _idempotent_job(session, key=key, request_payload=request_payload)
    if existing is not None:
        return JobAccepted(job_id=existing.id, status=existing.status)

    analysis = _find_analysis(
        session,
        operator=operator,
        fingerprint=payload.analysis_fingerprint,
        selection=selection,
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A successful matching analysis is required before registration",
        )
    output = cast(dict[str, Any], analysis.result["output"])
    try:
        source_format = SourceFormat(cast(str, output["source_format"]))
        detected_task_type = TaskType(cast(str, output["task_type"]))
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The matching analysis result is incomplete",
        ) from exc

    dataset = Dataset(
        name=payload.name,
        description=payload.description.strip(),
        status="scanning",
        created_by_id=operator.id,
    )
    source = DatasetSource(
        dataset=dataset,
        allowed_root_id=root.id,
        relative_path=payload.relative_path,
        normalized_path=str(source_path),
        source_format=source_format,
        task_type=detected_task_type,
        scan_status="analyzed",
        source_metadata={
            "categories": payload.categories,
            "split": payload.split.model_dump(),
            "analysis_fingerprint": payload.analysis_fingerprint,
            "analysis_job_id": analysis.id,
            "analysis": output,
            "source_version": None,
        },
    )
    session.add(source)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dataset name already exists",
        ) from exc

    job = BackgroundJob(
        business_object_id=dataset.id,
        job_type="dataset_registration",
        idempotency_key=key,
        status=JobStatus.PENDING,
        stage="pending",
        total_count=cast(int, output["image_count"]),
        result={
            "request": {
                **request_payload,
                "dataset_id": dataset.id,
                "dataset_source_id": source.id,
                "created_by_id": operator.id,
            }
        },
        created_by_id=operator.id,
    )
    session.add(job)
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=operator.id,
            action="dataset.registration_requested",
            resource_type="dataset",
            resource_id=dataset.id,
            details={"job_id": job.id, "source_id": source.id},
            ip_address=request.client.host if request.client else None,
        )
    )
    session.commit()
    try:
        _queue(request).enqueue_registration(job.id)
    except Exception as exc:
        _mark_enqueue_failed(session, job.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset registration could not be queued",
        ) from exc
    return JobAccepted(job_id=job.id, status=JobStatus.PENDING)


def _find_analysis(
    session: SessionDependency,
    *,
    operator: User,
    fingerprint: str,
    selection: dict[str, object],
) -> BackgroundJob | None:
    jobs = session.scalars(
        select(BackgroundJob).where(
            BackgroundJob.job_type == "dataset_analysis",
            BackgroundJob.status == JobStatus.SUCCEEDED,
            BackgroundJob.created_by_id == operator.id,
        )
    )
    for job in jobs:
        output = job.result.get("output")
        request = job.result.get("request")
        if (
            isinstance(output, dict)
            and output.get("valid") is True
            and output.get("fingerprint") == fingerprint
            and request == selection
        ):
            return job
    return None


def _mark_enqueue_failed(session: SessionDependency, job_id: str, error: Exception) -> None:
    session.rollback()
    job = session.get(BackgroundJob, job_id)
    if job is not None:
        job.status = JobStatus.FAILED
        job.stage = "queue_failed"
        job.error_summary = {"code": "queue_unavailable", "message": str(error)}
        session.commit()


@router.get("")
def list_datasets(
    session: SessionDependency,
    _: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    dataset_status: Literal[
        "scanning",
        "pending_annotation",
        "reviewing",
        "trainable",
        "validation_failed",
        "archived",
    ]
    | None = Query(default=None, alias="status"),
) -> dict[str, object]:
    dataset_query = select(Dataset)
    count_query = select(func.count()).select_from(Dataset)
    if search is not None and (term := search.strip()):
        escaped = _escape_like(term)
        predicate = or_(
            Dataset.name.ilike(f"%{escaped}%", escape="\\"),
            Dataset.description.ilike(f"%{escaped}%", escape="\\"),
        )
        dataset_query = dataset_query.where(predicate)
        count_query = count_query.where(predicate)
    if dataset_status is not None:
        dataset_query = dataset_query.where(Dataset.status == dataset_status)
        count_query = count_query.where(Dataset.status == dataset_status)

    total = session.scalar(count_query) or 0
    datasets = session.scalars(
        dataset_query
        .order_by(Dataset.updated_at.desc(), Dataset.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [_dataset_summary(session, dataset) for dataset in datasets],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: str,
    session: SessionDependency,
    _: CurrentUser,
) -> dict[str, object]:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    response = _dataset_summary(session, dataset)
    response["description"] = dataset.description
    response["sources"] = [
        {
            "id": source.id,
            "source_root_id": source.allowed_root_id,
            "relative_path": source.relative_path,
            "source_format": source.source_format.value,
            "task_type": source.task_type.value,
            "scan_status": source.scan_status,
        }
        for source in dataset.sources
    ]
    return response


@router.get("/{dataset_id}/versions")
def list_versions(
    dataset_id: str,
    session: SessionDependency,
    _: CurrentUser,
) -> dict[str, object]:
    _require_dataset(session, dataset_id)
    versions = session.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version_number.desc())
    ).all()
    return {
        "data": [_version_response(session, version) for version in versions],
        "meta": {"page": 1, "page_size": len(versions), "total": len(versions)},
    }


@router.get("/{dataset_id}/versions/{version_id}/items")
def list_items(
    dataset_id: str,
    version_id: str,
    session: SessionDependency,
    _: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=500),
    split: Literal["train", "val", "test"] | None = None,
    annotation_status: Literal["annotated", "unannotated", "partial"] | None = None,
) -> dict[str, object]:
    version = _require_version(session, dataset_id, version_id)
    item_query = select(DatasetItem).where(DatasetItem.version_id == version.id)
    count_query = (
        select(func.count())
        .select_from(DatasetItem)
        .where(DatasetItem.version_id == version.id)
    )
    if search is not None and (term := search.strip()):
        predicate = DatasetItem.relative_path.ilike(
            f"%{_escape_like(term)}%",
            escape="\\",
        )
        item_query = item_query.where(predicate)
        count_query = count_query.where(predicate)
    if split is not None:
        item_query = item_query.where(DatasetItem.split == split)
        count_query = count_query.where(DatasetItem.split == split)
    if annotation_status is not None:
        item_query = item_query.where(DatasetItem.status == annotation_status)
        count_query = count_query.where(DatasetItem.status == annotation_status)

    total = session.scalar(count_query) or 0
    items = session.scalars(
        item_query
        .order_by(DatasetItem.relative_path, DatasetItem.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [_item_response(item) for item in items],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


@router.get("/{dataset_id}/versions/{version_id}/items/{item_id}/media")
def get_item_media(
    dataset_id: str,
    version_id: str,
    item_id: str,
    request: Request,
    session: SessionDependency,
    _: CurrentUser,
) -> FileResponse:
    version = _require_version(session, dataset_id, version_id)
    item = session.scalar(
        select(DatasetItem).where(
            DatasetItem.id == item_id,
            DatasetItem.version_id == version.id,
        )
    )
    if item is None or version.root_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset item not found")
    root = request.app.state.settings.managed_data_root / version.root_path
    try:
        resolved_root = root.resolve(strict=True)
        relative = PurePosixPath(item.relative_path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in item.relative_path:
            raise ValueError
        candidate = resolved_root / relative
        cursor = resolved_root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError
        media = candidate.resolve(strict=True)
        if not media.is_relative_to(resolved_root) or not media.is_file():
            raise ValueError
    except (OSError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset media not found") from None
    return FileResponse(media, media_type=item.media_type, filename=Path(item.relative_path).name)


@router.post("/{dataset_id}/archive")
def archive_dataset(
    dataset_id: str,
    request: Request,
    session: SessionDependency,
    operator: DatasetOperator,
) -> dict[str, object]:
    dataset = _require_dataset(session, dataset_id)
    if dataset.status != "archived":
        dataset.status = "archived"
        session.add(
            AuditEvent(
                actor_user_id=operator.id,
                action="dataset.archived",
                resource_type="dataset",
                resource_id=dataset.id,
                details={},
                ip_address=request.client.host if request.client else None,
            )
        )
        session.commit()
        session.refresh(dataset)
    return _dataset_summary(session, dataset)


def _require_dataset(session: SessionDependency, dataset_id: str) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _require_version(
    session: SessionDependency,
    dataset_id: str,
    version_id: str,
) -> DatasetVersion:
    version = session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == version_id,
            DatasetVersion.dataset_id == dataset_id,
        )
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found")
    return version


def _dataset_summary(session: SessionDependency, dataset: Dataset) -> dict[str, object]:
    current = session.scalar(
        select(DatasetVersion)
        .where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.status == VersionStatus.READY,
        )
        .order_by(DatasetVersion.version_number.desc())
        .limit(1)
    )
    split_counts = {"train": 0, "val": 0, "test": 0}
    total_size = 0
    if current is not None:
        total_size = session.scalar(
            select(func.coalesce(func.sum(DatasetItem.file_size), 0)).where(
                DatasetItem.version_id == current.id
            )
        ) or 0
        rows = session.execute(
            select(DatasetItem.split, func.count())
            .where(DatasetItem.version_id == current.id)
            .group_by(DatasetItem.split)
        )
        for split, count in rows:
            if split in split_counts:
                split_counts[split] = count
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "status": dataset.status,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "created_by": dataset.created_by.name,
        "current_version": current.version_number if current else None,
        "current_version_id": current.id if current else None,
        "item_count": current.item_count if current else 0,
        "annotation_count": current.annotation_count if current else 0,
        "category_count": len(current.class_schema) if current else 0,
        "class_schema": current.class_schema if current else [],
        "category_counts": current.category_counts if current else {},
        "split_counts": split_counts,
        "total_size": total_size,
    }


def _version_response(
    session: SessionDependency,
    version: DatasetVersion,
) -> dict[str, object]:
    return {
        "id": version.id,
        "version_number": version.version_number,
        "parent_id": version.parent_id,
        "review_session_id": version.review_session_id,
        "status": version.status.value,
        "class_schema": version.class_schema,
        "category_counts": version.category_counts,
        "item_count": version.item_count,
        "annotation_count": version.annotation_count,
        "training_count": session.scalar(
            select(func.count())
            .select_from(TrainingRun)
            .where(TrainingRun.dataset_version_id == version.id)
        )
        or 0,
        "validation_result": version.validation_result,
        "created_by": version.created_by.name if version.created_by else None,
        "created_at": version.created_at,
    }


def _item_response(item: DatasetItem) -> dict[str, object]:
    return {
        "id": item.id,
        "sample_key": item.sample_key,
        "relative_path": item.relative_path,
        "media_type": item.media_type,
        "width": item.width,
        "height": item.height,
        "file_size": item.file_size,
        "sha256": item.sha256,
        "split": item.split,
        "status": item.status,
        "annotation_count": item.annotation_count,
        "group_key": item.group_key,
    }
