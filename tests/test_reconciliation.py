from label_platform.db.models import Dataset, DatasetVersion, ReviewSession, TrainingRun
from label_platform.domain.enums import (
    ReviewStatus,
    TaskType,
    TrainingStatus,
    VersionStatus,
)
from label_platform.reconciliation import reconcile_external_state
from sqlalchemy.orm import sessionmaker


class RecordingWorkflow:
    def __init__(self):
        self.ids = []

    def reconcile(self, item_id):
        self.ids.append(item_id)


def test_reconciliation_checks_only_active_bound_external_work(db_session, user):
    dataset = Dataset(name="reconcile", description="", created_by_id=user.id)
    version = DatasetVersion(
        dataset=dataset,
        version_number=1,
        status=VersionStatus.READY,
        class_schema=[{"id": 1, "name": "cargo"}],
    )
    review = ReviewSession(
        dataset=dataset,
        input_version=version,
        label_studio_project_id=7,
        label_studio_base_url="http://label.test",
        idempotency_key="reconcile-review",
        status=ReviewStatus.READY,
        recoverable_status=ReviewStatus.READY,
        config_hash="a" * 64,
        created_by_id=user.id,
    )
    run = TrainingRun(
        dataset=dataset,
        dataset_version=version,
        unitrain_run_id="remote-run-1",
        idempotency_key="reconcile-training",
        name="baseline",
        task_type=TaskType.DETECTION,
        export_profile="unitrain-coco-split-v1",
        config={"epochs": 10},
        status=TrainingStatus.RUNNING,
        total_epochs=10,
        created_by_id=user.id,
    )
    db_session.add_all([review, run])
    db_session.commit()
    review_id = review.id
    run_id = run.id
    review_workflow = RecordingWorkflow()
    training_workflow = RecordingWorkflow()
    session_factory = sessionmaker(bind=db_session.get_bind())

    result = reconcile_external_state(
        session_factory,
        review_workflow=review_workflow,  # type: ignore[arg-type]
        training_workflow=training_workflow,  # type: ignore[arg-type]
    )

    assert result.reviews_checked == 1
    assert result.training_runs_checked == 1
    assert review_workflow.ids == [review_id]
    assert training_workflow.ids == [run_id]
