import hashlib
import json

from label_platform.datasets.storage_migration import migrate_version_storage
from label_platform.db.models import Dataset, DatasetItem, DatasetVersion
from label_platform.domain.enums import VersionStatus


def test_migrates_legacy_version_to_blobs_and_single_json(
    api_context,
    image_factory,
):
    settings, session_factory = api_context
    version_root = settings.managed_data_root / "dataset-legacy/versions/v1"
    image_path = version_root / "images/frame.jpg"
    image_factory(image_path, size=(20, 10))
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    (version_root / "annotations").mkdir()
    (version_root / "splits").mkdir()
    coco = {
        "info": {"format": "platform-coco-v1"},
        "images": [
            {
                "id": 1,
                "file_name": "images/frame.jpg",
                "width": 20,
                "height": 10,
                "sample_key": "sample-1",
            }
        ],
        "annotations": [],
        "categories": [{"id": 1, "name": "cargo"}],
    }
    (version_root / "annotations/instances.coco.json").write_text(
        json.dumps(coco), encoding="utf-8"
    )
    for split, content in {"train": "sample-1\n", "val": "", "test": ""}.items():
        (version_root / f"splits/{split}.txt").write_text(content, encoding="utf-8")
    (version_root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "platform-coco-v1",
                "converter_version": "legacy",
                "task_type": "detection",
                "source_format": "image_directory",
                "categories": coco["categories"],
                "split_config": {
                    "seed": 42,
                    "ratios": {"train": 1.0, "val": 0.0, "test": 0.0},
                },
                "files": {
                    "images/frame.jpg": {"sha256": digest, "size": image_path.stat().st_size}
                },
            }
        ),
        encoding="utf-8",
    )
    with session_factory() as session, session.begin():
        dataset = Dataset(id="dataset-legacy", name="legacy", description="")
        version = DatasetVersion(
            id="version-legacy",
            dataset_id=dataset.id,
            version_number=1,
            root_path="dataset-legacy/versions/v1",
            manifest_path="manifest.json",
            annotation_path="annotations/instances.coco.json",
            class_schema=coco["categories"],
            category_counts={"1": 0},
            item_count=1,
            annotation_count=0,
            status=VersionStatus.READY,
            validation_result={"valid": True, "errors": []},
        )
        version.items.append(
            DatasetItem(
                sample_key="sample-1",
                relative_path="images/frame.jpg",
                media_type="image/jpeg",
                width=20,
                height=10,
                file_size=image_path.stat().st_size,
                sha256=digest,
                split="train",
                status="unannotated",
            )
        )
        dataset.versions.append(version)
        session.add(dataset)

    old_export = (
        settings.unitrain_export_root
        / "version-legacy/unitrain-coco-split-v1/train/frame.jpg"
    )
    old_export.parent.mkdir(parents=True)
    old_export.write_bytes(image_path.read_bytes())

    preview = migrate_version_storage(
        session_factory,
        managed_root=settings.managed_data_root,
        export_root=settings.unitrain_export_root,
        dry_run=True,
    )
    assert preview.migrated == 1
    assert not (version_root / "version.json").exists()

    result = migrate_version_storage(
        session_factory,
        managed_root=settings.managed_data_root,
        export_root=settings.unitrain_export_root,
        dry_run=False,
    )

    assert result.migrated == 1
    assert result.blobs_created == 1
    assert result.exports_rebuilt == 1
    assert {path.name for path in version_root.iterdir()} == {"version.json"}
    document = json.loads((version_root / "version.json").read_text(encoding="utf-8"))
    blob = settings.managed_data_root / ".blobs/sha256" / document["images"][0]["sha256"]
    assert blob.is_file()
    exported_images = list(
        (settings.unitrain_export_root / "version-legacy").rglob("*.jpg")
    )
    assert len(exported_images) == 1
    assert exported_images[0].is_symlink()
    with session_factory() as session:
        stored = session.get(DatasetVersion, "version-legacy")
        assert stored is not None
        assert stored.manifest_path == "version.json"
        assert stored.annotation_path == "version.json"
