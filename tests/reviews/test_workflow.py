import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sqlalchemy import select

from label_platform.datasets.service import DatasetRegistrationRequest, RegistrationService
from label_platform.datasets.versioning import (
    image_by_sample,
    load_version_document,
    resolve_version_image,
)
from label_platform.db.models import Dataset, DatasetVersion, ReviewSession, ReviewTaskBinding
from label_platform.domain.enums import ReviewStatus, TaskType, TrainingStatus
from label_platform.integrations.labelstudio import LabelStudioProgress
from label_platform.integrations.unitrain import UnitTrainRun
from label_platform.reviews.service import ReviewWorkflow
from label_platform.training.service import TrainingWorkflow


class FakeLabelStudioConnector:
    def __init__(self) -> None:
        self.tasks: dict[str, tuple[int, dict[str, object]]] = {}
        self.import_calls = 0
        self.deleted_projects: list[int] = []
        self.deleted_samples: set[str] = set()

    def health(self) -> str:
        return "1.13.1"

    def create_project(self, title: str, description: str) -> int:
        assert "warehouse" in title
        return 17

    def configure_labels(self, project_id: int, label_config: str) -> None:
        assert project_id == 17
        assert "RectangleLabels" in label_config

    def create_local_storage(self, project_id: int, version_path: str) -> int:
        assert "/.reviews/" in version_path
        assert version_path.endswith("/images")
        return 23

    def import_tasks(
        self,
        project_id: int,
        tasks: list[dict[str, object]],
    ) -> dict[str, int]:
        self.import_calls += 1
        imported: dict[str, int] = {}
        for payload in tasks:
            data = payload["data"]
            assert isinstance(data, dict)
            sample_key = data["sample_key"]
            assert isinstance(sample_key, str)
            task_id = 40 + len(self.tasks) + 1
            self.tasks[sample_key] = (task_id, copy.deepcopy(payload))
            imported[sample_key] = task_id
        return imported

    def get_task_bindings(self, project_id: int) -> dict[str, int]:
        return {sample: task_id for sample, (task_id, _) in self.tasks.items()}

    def get_review_url(self, project_id: int) -> str:
        return f"http://label.test/projects/{project_id}/data"

    def get_progress(self, project_id: int) -> LabelStudioProgress:
        return LabelStudioProgress(total=len(self.tasks), completed=len(self.tasks), skipped=0)

    def export_annotations(self, project_id: int, output_path: Path) -> Path:
        exported = []
        for sample_key, (task_id, payload) in self.tasks.items():
            task = copy.deepcopy(payload)
            task["id"] = task_id
            results = [
                {
                    "id": "human-box",
                    "from_name": "bbox",
                    "to_name": "image",
                    "type": "rectanglelabels",
                    "original_width": 20,
                    "original_height": 10,
                    "value": {
                        "x": 10,
                        "y": 10,
                        "width": 40,
                        "height": 50,
                        "rotation": 0,
                        "rectanglelabels": ["cargo"],
                    },
                }
            ]
            if sample_key in self.deleted_samples:
                results.append(
                    {
                        "from_name": "image_disposition",
                        "to_name": "image",
                        "type": "choices",
                        "value": {"choices": ["删除图片"]},
                    }
                )
            task["annotations"] = [
                {
                    "ground_truth": False,
                    "result": results,
                }
            ]
            exported.append(task)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(exported), encoding="utf-8")
        return output_path

    def archive_project(self, project_id: int) -> None:
        pass

    def delete_project(self, project_id: int) -> None:
        self.deleted_projects.append(project_id)


class FakeUnitTrainConnector:
    def __init__(self) -> None:
        self.payload = None

    def create_run(self, payload):
        self.payload = payload
        return UnitTrainRun(
            id="unitrain-e2e-1",
            status=TrainingStatus.RUNNING,
            detail_url="http://unitrain.test/runs/unitrain-e2e-1",
            current_epoch=0,
            total_epochs=2,
            metric_summary={},
            error=None,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
        )


def test_review_creation_is_resumable_and_export_publishes_one_child(
    api_context,
    image_factory,
    tmp_path,
):
    settings, session_factory = api_context
    with session_factory() as session, session.begin():
        dataset = Dataset(
            id="dataset-1",
            name="warehouse",
            description="cargo",
        )
        session.add(dataset)
    source = tmp_path / "source"
    image_factory(source / "frame.jpg", size=(20, 10))
    version = RegistrationService(
        session_factory,
        managed_root=settings.managed_data_root,
    ).register(
        DatasetRegistrationRequest(
            dataset_id="dataset-1",
            source_path=source,
            categories=("cargo",),
            task_type=TaskType.DETECTION,
            split_ratios={"train": 1.0, "val": 0.0, "test": 0.0},
        )
    )
    connector = FakeLabelStudioConnector()
    workflow = ReviewWorkflow(
        session_factory,
        managed_root=settings.managed_data_root,
        export_root=tmp_path / "exports",
        label_studio_mount_root=Path("/datasets"),
        label_studio_base_url="http://label.test",
        connector=connector,
    )

    review = workflow.create_session(
        dataset_id="dataset-1",
        input_version_id=version.id,
        idempotency_key="review-request-1",
    )
    repeated = workflow.create_session(
        dataset_id="dataset-1",
        input_version_id=version.id,
        idempotency_key="review-request-1",
    )
    workflow.run_creation(review.id)
    workflow.run_creation(review.id)

    with session_factory() as session:
        stored = session.get(ReviewSession, review.id)
        assert stored is not None
        assert stored.status is ReviewStatus.READY
        assert stored.label_studio_project_id == 17
        assert stored.label_studio_storage_id == 23
        bindings = session.scalars(
            select(ReviewTaskBinding).where(ReviewTaskBinding.review_session_id == review.id)
        ).all()
        assert len(bindings) == 1
    assert repeated.id == review.id
    assert connector.import_calls == 1
    review_image = settings.managed_data_root / ".reviews" / review.id / "images/frame.jpg"
    assert review_image.is_symlink()
    assert not Path(os.readlink(review_image)).is_absolute()
    version_root = settings.managed_data_root / version.root_path
    document = load_version_document(
        version_root,
        manifest_path=version.manifest_path,
        annotation_path=version.annotation_path,
    )
    source_image = image_by_sample(document)[next(iter(connector.tasks))]
    assert review_image.resolve() == resolve_version_image(
        settings.managed_data_root,
        version_root,
        source_image,
    ).resolve()

    workflow.start_export(review.id)
    output = workflow.run_export(review.id)
    repeated_output = workflow.run_export(review.id)

    assert repeated_output.id == output.id
    assert output.version_number == 2
    assert output.parent_id == version.id
    assert output.review_session_id == review.id
    assert output.annotation_count == 1
    assert not (settings.managed_data_root / ".reviews" / review.id).exists()
    with session_factory() as session:
        stored = session.get(ReviewSession, review.id)
        assert stored is not None
        assert stored.status is ReviewStatus.COMPLETED
        assert stored.output_version_id == output.id
        assert stored.raw_export_path is not None
        versions = session.scalars(
            select(DatasetVersion).where(DatasetVersion.dataset_id == "dataset-1")
        ).all()
        assert len(versions) == 2

    unitrain = FakeUnitTrainConnector()
    training = TrainingWorkflow(
        session_factory,
        managed_root=settings.managed_data_root,
        export_root=tmp_path / "unitrain-exports",
        unitrain_mount_root=tmp_path / "unitrain-exports",
        connector=unitrain,  # type: ignore[arg-type]
    )
    run = training.create_run(
        dataset_id="dataset-1",
        dataset_version_id=output.id,
        name="reviewed-baseline",
        config={
            "framework": "ultralytics",
            "model": "yolo11n",
            "epochs": 2,
            "batch_size": 1,
        },
        idempotency_key="training-after-review",
    )
    submitted = training.submit(run.id)

    assert submitted.status is TrainingStatus.RUNNING
    assert submitted.dataset_version_id == output.id
    assert unitrain.payload is not None
    assert unitrain.payload["dataset_version_id"] == output.id
    assert unitrain.payload["dataset_path"].endswith(
        f"{output.id}/unitrain-coco-split-v1"
    )
    assert output.status.value == "ready"


def test_review_delete_choice_publishes_filtered_child_and_preserves_parent(
    api_context,
    image_factory,
    tmp_path,
):
    settings, session_factory = api_context
    with session_factory() as session, session.begin():
        session.add(Dataset(id="dataset-delete", name="warehouse", description="cargo"))
    source = tmp_path / "delete-source"
    image_factory(source / "a.jpg", size=(20, 10))
    image_factory(source / "b.jpg", size=(20, 10))
    parent = RegistrationService(
        session_factory,
        managed_root=settings.managed_data_root,
    ).register(
        DatasetRegistrationRequest(
            dataset_id="dataset-delete",
            source_path=source,
            categories=("cargo",),
            task_type=TaskType.DETECTION,
            split_ratios={"train": 1.0, "val": 0.0, "test": 0.0},
        )
    )
    connector = FakeLabelStudioConnector()
    workflow = ReviewWorkflow(
        session_factory,
        managed_root=settings.managed_data_root,
        export_root=tmp_path / "delete-exports",
        label_studio_mount_root=Path("/datasets"),
        label_studio_base_url="http://label.test",
        connector=connector,
    )
    review = workflow.create_session(
        dataset_id="dataset-delete",
        input_version_id=parent.id,
        idempotency_key="delete-one",
    )
    workflow.run_creation(review.id)
    connector.deleted_samples.add(sorted(connector.tasks)[0])
    preview = workflow.preview_export(review.id)

    assert preview.input_version_number == 1
    assert preview.input_image_count == 2
    assert preview.input_annotation_count == 0
    assert preview.export_image_count == 1
    assert preview.export_annotation_count == 1
    assert not list((tmp_path / "delete-exports" / review.id).glob(".preview-*.json"))

    workflow.start_export(review.id)
    child = workflow.run_export(review.id)

    assert parent.item_count == 2
    assert child.item_count == 1
    assert child.annotation_count == 1
    parent_json = json.loads(
        (settings.managed_data_root / parent.root_path / "version.json").read_text(
            encoding="utf-8"
        )
    )
    child_json = json.loads(
        (settings.managed_data_root / child.root_path / "version.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(parent_json["images"]) == 2
    assert len(child_json["images"]) == 1
    assert {annotation["image_id"] for annotation in child_json["annotations"]} == {
        child_json["images"][0]["id"]
    }
