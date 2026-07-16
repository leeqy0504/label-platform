from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    DATA_ENGINEER = "data_engineer"
    REVIEWER = "reviewer"


class SourceFormat(StrEnum):
    IMAGE_DIRECTORY = "image_directory"
    COCO_DETECTION = "coco_detection"
    COCO_INSTANCE = "coco_instance"
    LABEL_STUDIO = "label_studio"


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
