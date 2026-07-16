from collections.abc import Callable
from typing import Protocol

from redis import Redis
from rq import Queue


class JobQueue(Protocol):
    def enqueue_analysis(self, job_id: str) -> None: ...

    def enqueue_registration(self, job_id: str) -> None: ...

    def enqueue_review_creation(self, job_id: str) -> None: ...

    def enqueue_review_export(self, job_id: str) -> None: ...

    def enqueue_training_submission(self, job_id: str) -> None: ...


class RQJobQueue:
    def __init__(self, redis_url: str) -> None:
        self.queue = Queue("dataset-operations", connection=Redis.from_url(redis_url))

    def enqueue_analysis(self, job_id: str) -> None:
        self.queue.enqueue("label_platform.jobs.tasks.run_analysis_job", job_id)

    def enqueue_registration(self, job_id: str) -> None:
        self.queue.enqueue("label_platform.jobs.tasks.run_registration_job", job_id)

    def enqueue_review_creation(self, job_id: str) -> None:
        self.queue.enqueue("label_platform.jobs.tasks.run_review_creation_job", job_id)

    def enqueue_review_export(self, job_id: str) -> None:
        self.queue.enqueue("label_platform.jobs.tasks.run_review_export_job", job_id)

    def enqueue_training_submission(self, job_id: str) -> None:
        self.queue.enqueue("label_platform.jobs.tasks.run_training_submission_job", job_id)


class InlineJobQueue:
    def __init__(
        self,
        *,
        analysis_handler: Callable[[str], object] | None = None,
        registration_handler: Callable[[str], object] | None = None,
        review_creation_handler: Callable[[str], object] | None = None,
        review_export_handler: Callable[[str], object] | None = None,
        training_submission_handler: Callable[[str], object] | None = None,
    ) -> None:
        self.analysis_handler = analysis_handler
        self.registration_handler = registration_handler
        self.review_creation_handler = review_creation_handler
        self.review_export_handler = review_export_handler
        self.training_submission_handler = training_submission_handler
        self.analysis_enqueued_count = 0
        self.registration_enqueued_count = 0
        self.review_creation_enqueued_count = 0
        self.review_export_enqueued_count = 0
        self.training_submission_enqueued_count = 0

    @property
    def enqueued_count(self) -> int:
        return (
            self.analysis_enqueued_count
            + self.registration_enqueued_count
            + self.review_creation_enqueued_count
            + self.review_export_enqueued_count
            + self.training_submission_enqueued_count
        )

    def enqueue_analysis(self, job_id: str) -> None:
        self.analysis_enqueued_count += 1
        if self.analysis_handler is not None:
            self.analysis_handler(job_id)

    def enqueue_registration(self, job_id: str) -> None:
        self.registration_enqueued_count += 1
        if self.registration_handler is not None:
            self.registration_handler(job_id)

    def enqueue_review_creation(self, job_id: str) -> None:
        self.review_creation_enqueued_count += 1
        if self.review_creation_handler is not None:
            self.review_creation_handler(job_id)

    def enqueue_review_export(self, job_id: str) -> None:
        self.review_export_enqueued_count += 1
        if self.review_export_handler is not None:
            self.review_export_handler(job_id)

    def enqueue_training_submission(self, job_id: str) -> None:
        self.training_submission_enqueued_count += 1
        if self.training_submission_handler is not None:
            self.training_submission_handler(job_id)
