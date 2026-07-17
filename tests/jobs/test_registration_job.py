import logging

from label_platform.jobs.queue import InlineJobQueue
from label_platform.jobs.tasks import JobRunner


def test_inline_queue_passes_only_job_id_to_handlers():
    analysis_ids = []
    registration_ids = []
    queue = InlineJobQueue(
        analysis_handler=analysis_ids.append,
        registration_handler=registration_ids.append,
    )

    queue.enqueue_analysis("analysis-job")
    queue.enqueue_registration("registration-job")
    queue.enqueue_training_submission("training-job")

    assert analysis_ids == ["analysis-job"]
    assert registration_ids == ["registration-job"]
    assert queue.analysis_enqueued_count == 1
    assert queue.registration_enqueued_count == 1
    assert queue.training_submission_enqueued_count == 1


def test_job_log_write_failure_does_not_abort_the_job(tmp_path, caplog):
    (tmp_path / "logs").write_text("blocks log directory creation", encoding="utf-8")
    runner = object.__new__(JobRunner)
    runner.log_root = tmp_path / "logs" / "jobs"

    with caplog.at_level(logging.WARNING):
        runner._append_log("job-1", "started")

    assert "Could not write background job log job-1" in caplog.text
