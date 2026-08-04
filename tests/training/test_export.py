from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from label_platform.datasets.image_adapter import ImageDirectoryAdapter
from label_platform.datasets.normalize import normalize_source
from label_platform.datasets.publisher import DatasetPublisher
from label_platform.training.export import UnitTrainExportError, UnitTrainExporter


def publish_version(image_factory, tmp_path):
    source = tmp_path / "source"
    image_factory(source / "camera-a" / "frame.jpg")
    image_factory(source / "camera-b" / "frame.jpg")
    adapted = ImageDirectoryAdapter().read(
        source,
        dataset_id="dataset-1",
        categories=["cargo"],
    )
    adapted = replace(
        adapted,
        images=(
            replace(adapted.images[0], split="train"),
            replace(adapted.images[1], split="val"),
        ),
    )
    canonical = normalize_source(
        adapted,
        split_ratios={"train": 0.5, "val": 0.5, "test": 0.0},
    )
    return DatasetPublisher(tmp_path / "managed").publish(
        canonical,
        dataset_id="dataset-1",
        version_number=1,
        version_id="version-1",
    ).version_root


def test_unitrain_export_is_separate_atomic_immutable_and_idempotent(image_factory, tmp_path):
    version_root = publish_version(image_factory, tmp_path)
    exporter = UnitTrainExporter(tmp_path / "exports")

    first = exporter.materialize(version_root, version_id="version-1")
    second = exporter.materialize(version_root, version_id="version-1")

    assert first.root == second.root
    assert first.annotation_path == "train/_annotations.coco.json"
    assert (first.root / "train/_annotations.coco.json").is_file()
    assert (first.root / "valid/_annotations.coco.json").is_file()
    assert (first.root / "test/_annotations.coco.json").is_file()
    assert not list((tmp_path / "exports").rglob("*.building"))
    assert (first.root / "export-manifest.json").stat().st_mode & 0o222 == 0
    exported_names = [path.name for path in first.root.rglob("*.jpg")]
    assert len(exported_names) == len(set(exported_names)) == 2
    assert all(path.is_symlink() for path in first.root.rglob("*.jpg"))
    assert all(
        not Path(os.readlink(path)).is_absolute() for path in first.root.rglob("*.jpg")
    )
    for split in ("train", "valid", "test"):
        coco = json.loads(
            (first.root / split / "_annotations.coco.json").read_text(encoding="utf-8")
        )
        assert all("/" not in image["file_name"] for image in coco["images"])


def test_unitrain_export_repairs_legacy_absolute_image_links(image_factory, tmp_path):
    version_root = publish_version(image_factory, tmp_path)
    exporter = UnitTrainExporter(tmp_path / "exports")
    first = exporter.materialize(version_root, version_id="version-1")
    image_link = next(first.root.rglob("*.jpg"))
    expected = image_link.resolve(strict=True)
    parent_mode = image_link.parent.stat().st_mode & 0o777
    image_link.parent.chmod(0o755)
    try:
        image_link.unlink()
        image_link.symlink_to(expected)
    finally:
        image_link.parent.chmod(parent_mode)

    exporter.materialize(version_root, version_id="version-1")

    assert image_link.is_symlink()
    assert not Path(os.readlink(image_link)).is_absolute()
    assert image_link.resolve(strict=True) == expected


def test_unitrain_export_rejects_split_overlap_without_exposing_partial_output(
    image_factory,
    tmp_path,
):
    version_root = publish_version(image_factory, tmp_path)
    version_json = version_root / "version.json"
    version_json.chmod(0o644)
    document = json.loads(version_json.read_text(encoding="utf-8"))
    document["images"][0]["split"] = "unknown"
    version_json.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(UnitTrainExportError, match="invalid image split"):
        UnitTrainExporter(tmp_path / "exports").materialize(
            version_root,
            version_id="version-1",
        )

    assert not (tmp_path / "exports/version-1/unitrain-coco-split-v1").exists()
