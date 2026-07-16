from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from label_platform.db.models import ReviewSession, TrainingRun
from label_platform.domain.enums import ReviewStatus, TrainingStatus
from label_platform.reviews.service import ReviewWorkflow
from label_platform.training.service import TrainingWorkflow


@dataclass(frozen=True)
class ReconciliationResult:
    reviews_checked: int
    training_runs_checked: int
    errors: tuple[str, ...]


def reconcile_external_state(
    session_factory: sessionmaker[Session],
    *,
    review_workflow: ReviewWorkflow,
    training_workflow: TrainingWorkflow,
) -> ReconciliationResult:
    with session_factory() as session:
        review_ids = list(
            session.scalars(
                select(ReviewSession.id).where(
                    ReviewSession.label_studio_project_id.is_not(None),
                    ReviewSession.status.in_([ReviewStatus.READY, ReviewStatus.IN_REVIEW]),
                )
            )
        )
        training_ids = list(
            session.scalars(
                select(TrainingRun.id).where(
                    TrainingRun.unitrain_run_id.is_not(None),
                    TrainingRun.status.in_([TrainingStatus.QUEUED, TrainingStatus.RUNNING]),
                )
            )
        )
    errors: list[str] = []
    for review_id in review_ids:
        try:
            review_workflow.reconcile(review_id)
        except Exception as exc:
            errors.append(f"review {review_id}: {exc}")
    for run_id in training_ids:
        try:
            training_workflow.reconcile(run_id)
        except Exception as exc:
            errors.append(f"training {run_id}: {exc}")
    return ReconciliationResult(
        reviews_checked=len(review_ids),
        training_runs_checked=len(training_ids),
        errors=tuple(errors),
    )
