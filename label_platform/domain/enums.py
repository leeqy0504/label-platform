from enum import StrEnum


class SourceFormat(StrEnum):
    IMAGE_DIRECTORY = "image_directory"
    COCO_DETECTION = "coco_detection"
    COCO_INSTANCE = "coco_instance"
    LABEL_STUDIO = "label_studio"
    YOLO_DETECTION = "yolo_detection"


class TaskType(StrEnum):
    DETECTION = "detection"
    INSTANCE_SEGMENTATION = "instance_segmentation"


class VersionStatus(StrEnum):
    BUILDING = "building"
    VALIDATING = "validating"
    READY = "ready"
    INVALID = "invalid"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewStatus(StrEnum):
    CREATING = "creating"
    IMPORTING = "importing"
    READY = "ready"
    IN_REVIEW = "in_review"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"


class TrainingStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
