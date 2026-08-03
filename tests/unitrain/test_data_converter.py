import hashlib
import json
from pathlib import Path

import numpy as np
from pycocotools import mask as mask_utils

from unitrain.data_converter import convert_coco_dataset


def _write_split(image_factory, root: Path, split: str, image_id: int | None) -> None:
    split_root = root / split
    split_root.mkdir(parents=True)
    images: list[dict[str, object]] = []
    annotations: list[dict[str, object]] = []
    if image_id is not None:
        image_name = f"mouse-{image_id}.png"
        image_factory(split_root / image_name, size=(32, 24))
        mask = np.zeros((24, 32), dtype=np.uint8)
        mask[4:20, 6:26] = 1
        encoded = mask_utils.encode(np.asfortranarray(mask))
        counts = encoded["counts"]
        if isinstance(counts, bytes):
            counts = counts.decode("utf-8")
        images.append({"id": image_id, "file_name": image_name, "width": 32, "height": 24})
        annotations.append(
            {
                "id": image_id,
                "image_id": image_id,
                "category_id": 1,
                "bbox": [6, 4, 20, 16],
                "area": 320,
                "iscrowd": 0,
                "segmentation": {"size": [24, 32], "counts": counts},
            }
        )
    payload = {
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": "object"}],
    }
    (split_root / "_annotations.coco.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_yolo_rle_conversion_uses_writable_output_for_temporary_files(
    image_factory,
    tmp_path: Path,
) -> None:
    source = tmp_path / "readonly-coco"
    _write_split(image_factory, source, "train", 1)
    _write_split(image_factory, source, "valid", 2)
    _write_split(image_factory, source, "test", None)
    before_digest = _tree_digest(source)

    files = [path for path in source.rglob("*") if path.is_file()]
    directories = [source, *(path for path in source.rglob("*") if path.is_dir())]
    for path in files:
        path.chmod(0o444)
    for path in directories:
        path.chmod(0o555)

    output = tmp_path / "prepared-yolo"
    try:
        result = convert_coco_dataset(source, output, task="segment", framework="yolo")

        assert result == {"nc": 1, "names": ["object"]}
        assert _tree_digest(source) == before_digest
        assert all(path.stat().st_mode & 0o222 == 0 for path in files)
        assert all(path.stat().st_mode & 0o222 == 0 for path in directories)
        assert not list(source.rglob("*_temp_annotations.json"))
        assert not list(output.glob("*_temp_annotations.json"))
        for split in ("train", "val"):
            labels = list((output / "labels" / split).glob("*.txt"))
            assert len(labels) == 1
            fields = labels[0].read_text(encoding="utf-8").strip().split()
            assert fields[0] == "0"
            assert len(fields) >= 7
            assert (len(fields) - 1) % 2 == 0
        assert (output / "images" / "test").is_dir()
    finally:
        for path in directories:
            path.chmod(0o755)
        for path in files:
            path.chmod(0o644)

