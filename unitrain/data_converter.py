"""Data format converter using supervision library.

Uses Supervision's COCO and YOLO format helpers for annotation conversion while
keeping image storage read-only and free of copied image payloads.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from pycocotools import mask as mask_utils
from supervision.dataset.formats.coco import (
    build_coco_class_index_mapping,
    coco_annotations_to_detections,
    coco_categories_to_classes,
    group_coco_annotations_by_image_id,
)
from supervision.dataset.formats.yolo import (
    detections_to_yolo_annotations,
    save_data_yaml,
)
from supervision.dataset.utils import map_detections_class_id
from supervision.utils.file import save_text_file


def _preprocess_rle_annotations(
    annotations_path: str,
    *,
    temporary_directory: Path,
    convert_rle: bool = True,
) -> str:
    """预处理 COCO 标注文件。
    
    - 如果 convert_rle=True：将 RLE 格式转换为 polygon 格式（用于不支持 RLE 的框架如 YOLO）
    - 如果 convert_rle=False：保留 RLE 格式（用于支持 RLE 的框架如 RF-DETR）
    - 始终将嵌套格式 [[x1,y1,...]] 展平为 [x1,y1,...] 以兼容 supervision 库
    
    Args:
        annotations_path: COCO JSON 标注文件路径
        temporary_directory: 可写的临时文件目录
        convert_rle: 是否将 RLE 转换为 polygon，默认 True
        
    Returns:
        处理后的标注文件路径（如果有修改则返回临时文件路径，否则返回原路径）
    """
    with open(annotations_path, 'r') as f:
        coco_data = json.load(f)
    
    has_changes = False
    rle_count = 0
    flatten_count = 0
    
    # 检查并转换 RLE 格式的 segmentation
    for ann in coco_data['annotations']:
        if 'segmentation' not in ann:
            continue
            
        seg = ann['segmentation']
        
        # 检测 RLE 格式: {"counts": ..., "size": ...}
        if isinstance(seg, dict) and 'counts' in seg:
            if not convert_rle:
                # 保留 RLE 格式，跳过转换
                rle_count += 1
                continue
            
            has_changes = True
            rle_count += 1
            
            try:
                # 解码 RLE 为二值 mask
                if isinstance(seg['counts'], list):
                    # 未压缩的 RLE
                    rle = mask_utils.frPyObjects(seg, seg['size'][0], seg['size'][1])
                else:
                    # 压缩的 RLE
                    rle = seg
                
                mask = mask_utils.decode(rle)
                
                # 使用 OpenCV 提取轮廓
                contours, _ = cv2.findContours(
                    mask.astype(np.uint8),
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE
                )
                
                if contours:
                    # 只保留最大的轮廓（按面积）避免多轮廓导致的 inhomogeneous shape 错误
                    largest_contour = max(contours, key=cv2.contourArea)
                    
                    if len(largest_contour) >= 3:  # 至少需要 3 个点
                        polygon = largest_contour.flatten().tolist()
                        # 确保所有坐标都是 float（与原始 COCO polygon 格式一致）
                        polygon = [float(x) for x in polygon]
                        # supervision 期望 segmentation 是单个扁平列表，不是嵌套列表
                        ann['segmentation'] = polygon
                    else:
                        # 回退到 bbox
                        x, y, w, h = ann['bbox']
                        ann['segmentation'] = [float(x), float(y), float(x+w), float(y), 
                                              float(x+w), float(y+h), float(x), float(y+h)]
                else:
                    # 没有找到轮廓，使用 bbox
                    x, y, w, h = ann['bbox']
                    ann['segmentation'] = [float(x), float(y), float(x+w), float(y), 
                                          float(x+w), float(y+h), float(x), float(y+h)]
                    
            except Exception as e:
                print(f"  [WARNING] 转换 RLE 失败 (annotation {ann.get('id', 'unknown')}): {e}, 使用 bbox")
                x, y, w, h = ann['bbox']
                ann['segmentation'] = [float(x), float(y), float(x+w), float(y), 
                                      float(x+w), float(y+h), float(x), float(y+h)]
        
        # 展平嵌套的 polygon 格式: [[x1,y1,...]] -> [x1,y1,...]
        # supervision 0.27.x 期望扁平列表而不是嵌套列表
        elif isinstance(seg, list) and seg and isinstance(seg[0], list):
            if len(seg) == 1:
                # 单个 polygon，直接展平
                ann['segmentation'] = seg[0]
                has_changes = True
                flatten_count += 1
            else:
                # 多个 polygon（多部分对象），合并为单个或取最大的
                # 为简单起见，取第一个（通常是最大的）
                print(f"  [INFO] 标注 {ann.get('id', 'unknown')} 有 {len(seg)} 个 polygon，仅保留第一个")
                ann['segmentation'] = seg[0]
                has_changes = True
                flatten_count += 1
    
    if rle_count > 0:
        if convert_rle:
            print(f"  已转换 {rle_count} 个 RLE 标注为 polygon 格式")
        else:
            print(f"  保留 {rle_count} 个 RLE 标注（框架原生支持）")
    if flatten_count > 0:
        print(f"  已展平 {flatten_count} 个嵌套 polygon 标注")
    
    if has_changes:
        temporary_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='_temp_annotations.json',
            delete=False,
            dir=temporary_directory,
        ) as f:
            json.dump(coco_data, f)
            return f.name
    
    return annotations_path


def _convert_split(
    images_dir: str,
    annotations_path: str,
    yolo_root: Path,
    split_name: str,
    force_masks: bool = False,
    convert_rle: bool = True,
) -> list[str]:
    """Load one COCO split and export it as YOLO.
    
    Args:
        convert_rle: 是否将 RLE 转换为 polygon。YOLO 需要 True，RF-DETR 可以 False。
    """
    # 预处理标注格式
    processed_ann_path = _preprocess_rle_annotations(
        annotations_path,
        temporary_directory=yolo_root,
        convert_rle=convert_rle,
    )
    
    try:
        with Path(processed_ann_path).open(encoding="utf-8") as annotation_file:
            coco = json.load(annotation_file)
        classes = coco_categories_to_classes(coco["categories"])
        class_mapping = build_coco_class_index_mapping(
            coco_categories=coco["categories"],
            target_classes=classes,
        )
        annotations_by_image = group_coco_annotations_by_image_id(coco["annotations"])
        labels_root = yolo_root / "labels" / split_name
        labels_root.mkdir(parents=True, exist_ok=True)
        source_root = Path(images_dir).resolve(strict=True)
        image_view = yolo_root / "images" / split_name
        if image_view.is_symlink():
            image_view.unlink()
        if image_view.exists() and not image_view.is_dir():
            raise RuntimeError(f"YOLO image view is not a directory: {image_view}")
        image_view.mkdir(parents=True, exist_ok=True)
        for image in coco["images"]:
            file_name = image["file_name"]
            if not isinstance(file_name, str) or Path(file_name).name != file_name:
                raise RuntimeError("UnitTrain COCO export image names must be flat")
            source_image = source_root / file_name
            try:
                resolved_image = source_image.resolve(strict=True)
            except OSError as exc:
                raise RuntimeError(
                    f"Cannot access UnitTrain COCO image link target: {file_name}"
                ) from exc
            if not resolved_image.is_file():
                raise RuntimeError(f"UnitTrain COCO image is missing: {file_name}")
            image_link = image_view / file_name
            expected_target = Path(
                os.path.relpath(resolved_image, start=image_link.parent)
            )
            if image_link.exists() or image_link.is_symlink():
                if (
                    not image_link.is_symlink()
                    or Path(os.readlink(image_link)) != expected_target
                ):
                    raise RuntimeError(
                        f"YOLO image link already exists with another target: {file_name}"
                    )
            else:
                image_link.symlink_to(expected_target)
            width = image["width"]
            height = image["height"]
            image_annotations = annotations_by_image.get(image["id"], [])
            with_masks = force_masks or any(
                bool(annotation.get("segmentation"))
                for annotation in image_annotations
            )
            detections = coco_annotations_to_detections(
                image_annotations=image_annotations,
                resolution_wh=(width, height),
                with_masks=with_masks,
            )
            detections = map_detections_class_id(
                source_to_target_mapping=class_mapping,
                detections=detections,
            )
            lines = detections_to_yolo_annotations(
                detections=detections,
                image_shape=(height, width, 3),
                approximation_percentage=0.0,
            )
            save_text_file(
                lines=lines,
                file_path=str(labels_root / f"{Path(file_name).stem}.txt"),
            )
        save_data_yaml(
            data_yaml_path=str(yolo_root / "data.yaml"),
            classes=classes,
        )
    finally:
        # 清理临时文件
        if processed_ann_path != annotations_path:
            Path(processed_ann_path).unlink(missing_ok=True)
    
    return classes


def convert_roboflow_coco_dataset(
    coco_root: Path, yolo_root: Path, task: str = "detect", framework: str = "yolo"
) -> dict:
    """
    Convert Roboflow COCO format to YOLO format.

    Roboflow COCO structure (flat):
        coco_root/
        ├── train/
        │   ├── image1.jpg
        │   └── _annotations.coco.json
        ├── valid/
        │   └── _annotations.coco.json
        └── test/  (optional)

    Args:
        framework: 目标框架，"yolo" 需要转换 RLE，"rfdetr" 保留 RLE

    Returns:
        dict with 'nc' (num classes) and 'names' (class names)
    """
    split_map = {"train": "train", "valid": "val", "val": "val", "test": "test"}
    force_masks = task == "segment"
    # YOLO 不支持 RLE，需要转换；RF-DETR 原生支持 RLE，可保留
    convert_rle = framework.lower() in ("yolo", "ultralytics")
    class_info: dict = {"nc": 0, "names": []}

    for src_split, dst_split in split_map.items():
        split_dir = coco_root / src_split
        ann_file = split_dir / "_annotations.coco.json"
        if not ann_file.exists():
            continue

        print(f"  Converting {src_split} -> {dst_split} (task={task}, framework={framework})")
        classes = _convert_split(
            images_dir=str(split_dir),
            annotations_path=str(ann_file),
            yolo_root=yolo_root,
            split_name=dst_split,
            force_masks=force_masks,
            convert_rle=convert_rle,
        )

        if class_info["nc"] == 0:
            class_info["nc"] = len(classes)
            class_info["names"] = list(classes)

    # 修复 data.yaml：supervision 生成的 yaml 缺少路径信息
    data_yaml = yolo_root / "data.yaml"
    if data_yaml.exists():
        import yaml
        with open(data_yaml, 'r') as f:
            yaml_data = yaml.safe_load(f)
        
        # 添加路径信息（使用绝对路径）
        yaml_data['path'] = str(yolo_root.absolute())
        yaml_data['train'] = 'images/train'
        yaml_data['val'] = 'images/val'
        if (yolo_root / 'images' / 'test').exists():
            yaml_data['test'] = 'images/test'
        
        with open(data_yaml, 'w') as f:
            yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

    return class_info


def convert_coco_dataset(
    coco_root: Path, yolo_root: Path, task: str = "detect", framework: str = "yolo"
) -> dict | None:
    """
    Convert a full COCO dataset to YOLO format.
    Auto-detects: standard COCO or Roboflow COCO.

    Standard COCO:
        coco_root/
        ├── images/{train,val}/
        └── annotations/{train,val}.json

    Roboflow COCO:
        coco_root/
        ├── train/_annotations.coco.json
        └── valid/_annotations.coco.json

    Args:
        framework: 目标框架。"yolo"/"ultralytics" 需要转换 RLE 为 polygon，
                   "rfdetr" 等保留 RLE 格式（框架原生支持）

    Returns:
        dict with 'nc' and 'names' for Roboflow format, None for standard.
    """
    # Roboflow format
    if (coco_root / "train" / "_annotations.coco.json").exists():
        print("  Detected Roboflow COCO format")
        return convert_roboflow_coco_dataset(coco_root, yolo_root, task=task, framework=framework)

    # Standard COCO format
    force_masks = task == "segment"
    convert_rle = framework.lower() in ("yolo", "ultralytics")
    for split in ("train", "val"):
        ann_file = coco_root / "annotations" / f"{split}.json"
        images_dir = coco_root / "images" / split
        if ann_file.exists() and images_dir.exists():
            print(f"  Converting {split} (task={task}, framework={framework})")
            _convert_split(
                images_dir=str(images_dir),
                annotations_path=str(ann_file),
                yolo_root=yolo_root,
                split_name=split,
                force_masks=force_masks,
                convert_rle=convert_rle,
            )

    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert COCO to YOLO format")
    parser.add_argument("--input", required=True, help="COCO dataset root")
    parser.add_argument("--output", required=True, help="YOLO dataset output root")
    parser.add_argument("--task", default="detect", choices=["detect", "segment", "obb"])
    args = parser.parse_args()

    if args.task == "obb":
        print("OBB data should already be in YOLO OBB format. No conversion needed.")
        sys.exit(0)

    convert_coco_dataset(Path(args.input), Path(args.output), task=args.task)
    print(f"Converted {args.input} -> {args.output}")
