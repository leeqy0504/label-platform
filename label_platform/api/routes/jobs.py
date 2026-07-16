from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from label_platform.api.dependencies import CurrentUser, SessionDependency, require_roles
from label_platform.db.models import AuditEvent, BackgroundJob, TrainingRun, User
from label_platform.domain.enums import JobStatus, TrainingStatus, UserRole
from label_platform.jobs.queue import JobQueue


router = APIRouter(prefix="/api/jobs", tags=["jobs"])
JobOperator = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
]


class JobResponse(BaseModel):
    id: str
    business_object_id: str | None
    job_type: str
    status: JobStatus
    stage: str
    processed_count: int
    total_count: int
    result: dict[str, Any]
    error_summary: dict[str, Any]
    retry_count: int
    log_path: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _job_response(job: BackgroundJob) -> JobResponse:
    output = job.result.get("output")
    return JobResponse(
        id=job.id,
        business_object_id=job.business_object_id,
        job_type=job.job_type,
        status=job.status,
        stage=job.stage,
        processed_count=job.processed_count,
        total_count=job.total_count,
        result=cast(dict[str, Any], output) if isinstance(output, dict) else {},
        error_summary=job.error_summary,
        retry_count=job.retry_count,
        log_path=job.log_path,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    session: SessionDependency,
    _: CurrentUser,
) -> JobResponse:
    job = session.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Background job not found")
    return _job_response(job)


@router.post("/{job_id}/retry", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: str,
    request: Request,
    session: SessionDependency,
    operator: JobOperator,
) -> JobResponse:
    job = session.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Background job not found")
    if job.status is not JobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only failed jobs can be retried",
        )
    if job.job_type not in {
        "dataset_analysis",
        "dataset_registration",
        "training_submission",
    }:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job type cannot be retried")
    if job.job_type == "training_submission":
        run = (
            session.get(TrainingRun, job.business_object_id)
            if job.business_object_id is not None
            else None
        )
        if run is None or run.unitrain_run_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Submitted UnitTrain runs cannot be retried as a submission",
            )
        run.status = TrainingStatus.QUEUED
        run.error_summary = {}
        run.completed_at = None
    job.status = JobStatus.PENDING
    job.stage = "pending"
    job.started_at = None
    job.finished_at = None
    job.processed_count = 0
    job.error_summary = {}
    job.retry_count += 1
    session.add(
        AuditEvent(
            actor_user_id=operator.id,
            action="background_job.retried",
            resource_type="background_job",
            resource_id=job.id,
            details={"retry_count": job.retry_count},
            ip_address=request.client.host if request.client else None,
        )
    )
    session.commit()
    session.refresh(job)

    queue = cast(JobQueue, request.app.state.job_queue)
    try:
        if job.job_type == "dataset_analysis":
            queue.enqueue_analysis(job.id)
        elif job.job_type == "dataset_registration":
            queue.enqueue_registration(job.id)
        else:
            queue.enqueue_training_submission(job.id)
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.stage = "queue_failed"
        job.error_summary = {"code": "queue_unavailable", "message": str(exc)}
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background job could not be queued",
        ) from exc
    session.refresh(job)
    return _job_response(job)
