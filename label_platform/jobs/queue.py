from collections.abc import Callable
from typing import Protocol

from redis import Redis
from rq import Queue


class JobQueue(Protocol):
    def enqueue_analysis(self, job_id: str) -> None: ...

    def enqueue_registration(self, job_id: str) -> None: ...


class RQJobQueue:
    def __init__(self, redis_url: str) -> None:
        self.queue = Queue("dataset-operations", connection=Redis.from_url(redis_url))

    def enqueue_analysis(self, job_id: str) -> None:
        self.queue.enqueue("label_platform.jobs.tasks.run_analysis_job", job_id)

    def enqueue_registration(self, job_id: str) -> None:
        self.queue.enqueue("label_platform.jobs.tasks.run_registration_job", job_id)


class InlineJobQueue:
    def __init__(
        self,
        *,
        analysis_handler: Callable[[str], object] | None = None,
        registration_handler: Callable[[str], object] | None = None,
    ) -> None:
        self.analysis_handler = analysis_handler
        self.registration_handler = registration_handler
        self.analysis_enqueued_count = 0
        self.registration_enqueued_count = 0

    @property
    def enqueued_count(self) -> int:
        return self.analysis_enqueued_count + self.registration_enqueued_count

    def enqueue_analysis(self, job_id: str) -> None:
        self.analysis_enqueued_count += 1
        if self.analysis_handler is not None:
            self.analysis_handler(job_id)

    def enqueue_registration(self, job_id: str) -> None:
        self.registration_enqueued_count += 1
        if self.registration_handler is not None:
            self.registration_handler(job_id)
