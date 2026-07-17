from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from label_platform.api.dependencies import CurrentUser, SessionDependency, require_roles
from label_platform.db.models import BackgroundJob, Dataset, ReviewSession, User
from label_platform.domain.enums import JobStatus, ReviewStatus, UserRole
from label_platform.integrations.labelstudio import LabelStudioConnector
from label_platform.jobs.queue import JobQueue
from label_platform.reviews.service import (
    ReviewConflictError,
    ReviewWorkflow,
    ReviewWorkflowError,
)


router = APIRouter(prefix="/api/reviews", tags=["reviews"])
integration_router = APIRouter(prefix="/api/integrations/label-studio", tags=["integrations"])
ReviewOperator = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
]


class CreateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    input_version_id: str
    idempotency_key: str = Field(min_length=1, max_length=180)


class ReviewResponse(BaseModel):
    id: str
    dataset_id: str
    dataset_name: str
    input_version_id: str
    input_version_number: int
    output_version_id: str | None
    output_version_number: int | None
    label_studio_project_id: int | None
    label_studio_project_url: str | None
    total_tasks: int
    completed_tasks: int
    skipped_tasks: int
    status: ReviewStatus
    config_hash: str
    error_summary: dict[str, object]
    created_by: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    job_id: str | None = None


def _workflow(request: Request) -> ReviewWorkflow:
    settings = request.app.state.settings
    return ReviewWorkflow(
        request.app.state.session_factory,
        managed_root=settings.managed_data_root,
        export_root=settings.label_studio_export_root,
        label_studio_mount_root=settings.label_studio_mount_root,
        label_studio_base_url=settings.label_studio_public_url,
        connector=cast(LabelStudioConnector, request.app.state.label_studio_connector),
    )


@router.post("", response_model=ReviewResponse, status_code=status.HTTP_202_ACCEPTED)
def create_review(
    payload: CreateReviewRequest,
    request: Request,
    session: SessionDependency,
    operator: ReviewOperator,
) -> ReviewResponse:
    try:
        review = _workflow(request).create_session(
            dataset_id=payload.dataset_id,
            input_version_id=payload.input_version_id,
            created_by_id=operator.id,
            idempotency_key=f"{operator.id}:{payload.idempotency_key}",
        )
    except ReviewConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ReviewWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    session.expire_all()
    job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.business_object_id == review.id,
            BackgroundJob.job_type == "review_creation",
        )
    )
    if job is None:
        job = BackgroundJob(
            business_object_id=review.id,
            job_type="review_creation",
            idempotency_key=f"review-creation:{review.id}",
            status=JobStatus.PENDING,
            stage="pending",
            result={"request": {"review_session_id": review.id}},
            created_by_id=operator.id,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        try:
            cast(JobQueue, request.app.state.job_queue).enqueue_review_creation(job.id)
        except Exception as exc:
            _queue_failed(session, job, exc)
            _workflow(request).fail_session(review.id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Review creation could not be queued",
            ) from exc
    session.expire_all()
    stored = _require_review(session, review.id)
    return _review_response(stored, job_id=job.id)


@router.get("")
def list_reviews(
    session: SessionDependency,
    _: CurrentUser,
    dataset_id: str | None = None,
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    query = select(ReviewSession)
    count_query = select(func.count()).select_from(ReviewSession)
    if dataset_id is not None:
        query = query.where(ReviewSession.dataset_id == dataset_id)
        count_query = count_query.where(ReviewSession.dataset_id == dataset_id)
    if search is not None and (term := search.strip()):
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        predicate = Dataset.name.ilike(f"%{escaped}%", escape="\\")
        query = query.join(Dataset, Dataset.id == ReviewSession.dataset_id).where(
            predicate
        )
        count_query = count_query.join(
            Dataset,
            Dataset.id == ReviewSession.dataset_id,
        ).where(
            predicate
        )
    total = session.scalar(count_query) or 0
    reviews = session.scalars(
        query
        .order_by(ReviewSession.created_at.desc(), ReviewSession.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [
            _review_response(
                review,
                job_id=_latest_job_id(session, review.id),
            ).model_dump()
            for review in reviews
        ],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


@router.get("/{review_id}", response_model=ReviewResponse)
def get_review(
    review_id: str,
    session: SessionDependency,
    _: CurrentUser,
) -> ReviewResponse:
    return _review_response(_require_review(session, review_id), job_id=_latest_job_id(session, review_id))


@router.post("/{review_id}/sync", response_model=ReviewResponse)
def sync_review(
    review_id: str,
    request: Request,
    session: SessionDependency,
    _: CurrentUser,
) -> ReviewResponse:
    try:
        _workflow(request).reconcile(review_id)
    except ReviewWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    session.expire_all()
    return _review_response(_require_review(session, review_id), job_id=_latest_job_id(session, review_id))


@router.post("/{review_id}/complete", response_model=ReviewResponse, status_code=status.HTTP_202_ACCEPTED)
def complete_review(
    review_id: str,
    request: Request,
    session: SessionDependency,
    operator: ReviewOperator,
) -> ReviewResponse:
    job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.business_object_id == review_id,
            BackgroundJob.job_type == "review_export",
        )
    )
    if job is not None and job.status is JobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Failed review export must be retried explicitly",
        )
    try:
        _workflow(request).start_export(review_id)
    except ReviewConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ReviewWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.expire_all()
    if job is None:
        job = BackgroundJob(
            business_object_id=review_id,
            job_type="review_export",
            idempotency_key=f"review-export:{review_id}",
            status=JobStatus.PENDING,
            stage="pending",
            result={"request": {"review_session_id": review_id}},
            created_by_id=operator.id,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        try:
            cast(JobQueue, request.app.state.job_queue).enqueue_review_export(job.id)
        except Exception as exc:
            _queue_failed(session, job, exc)
            _workflow(request).fail_session(
                review_id,
                exc,
                recoverable=ReviewStatus.EXPORTING,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Review export could not be queued",
            ) from exc
    session.expire_all()
    return _review_response(_require_review(session, review_id), job_id=job.id)


@router.post("/{review_id}/retry", response_model=ReviewResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_review(
    review_id: str,
    request: Request,
    session: SessionDependency,
    _: ReviewOperator,
) -> ReviewResponse:
    try:
        review = _workflow(request).prepare_retry(review_id)
    except ReviewConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ReviewWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    job_type = "review_export" if review.status is ReviewStatus.EXPORTING else "review_creation"
    session.expire_all()
    job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.business_object_id == review_id,
            BackgroundJob.job_type == job_type,
        )
    )
    if job is None or job.status is not JobStatus.FAILED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Failed review job not found")
    job.status = JobStatus.PENDING
    job.stage = "pending"
    job.started_at = None
    job.finished_at = None
    job.error_summary = {}
    job.processed_count = 0
    job.retry_count += 1
    session.commit()
    queue = cast(JobQueue, request.app.state.job_queue)
    try:
        if job_type == "review_export":
            queue.enqueue_review_export(job.id)
        else:
            queue.enqueue_review_creation(job.id)
    except Exception as exc:
        _queue_failed(session, job, exc)
        _workflow(request).fail_session(review_id, exc, recoverable=review.status)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Retry failed") from exc
    session.expire_all()
    return _review_response(_require_review(session, review_id), job_id=job.id)


@integration_router.get("/health")
def label_studio_health(request: Request, _: CurrentUser) -> dict[str, str]:
    connector = cast(LabelStudioConnector, request.app.state.label_studio_connector)
    try:
        return {"status": "online", "version": connector.health()}
    except Exception:
        return {"status": "offline", "version": ""}


def _require_review(session: SessionDependency, review_id: str) -> ReviewSession:
    review = session.get(ReviewSession, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return review


def _review_response(review: ReviewSession, *, job_id: str | None = None) -> ReviewResponse:
    project_url = (
        f"{review.label_studio_base_url}/projects/{review.label_studio_project_id}/data"
        if review.label_studio_project_id is not None
        else None
    )
    return ReviewResponse(
        id=review.id,
        dataset_id=review.dataset_id,
        dataset_name=review.dataset.name,
        input_version_id=review.input_version_id,
        input_version_number=review.input_version.version_number,
        output_version_id=review.output_version_id,
        output_version_number=(
            review.output_version.version_number if review.output_version is not None else None
        ),
        label_studio_project_id=review.label_studio_project_id,
        label_studio_project_url=project_url,
        total_tasks=review.total_tasks,
        completed_tasks=review.completed_tasks,
        skipped_tasks=review.skipped_tasks,
        status=review.status,
        config_hash=review.config_hash,
        error_summary=cast(dict[str, object], review.error_summary),
        created_by=review.created_by.name,
        started_at=review.started_at,
        completed_at=review.completed_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
        job_id=job_id,
    )


def _latest_job_id(session: SessionDependency, review_id: str) -> str | None:
    return session.scalar(
        select(BackgroundJob.id)
        .where(BackgroundJob.business_object_id == review_id)
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
