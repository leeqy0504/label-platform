from label_platform.jobs.queue import InlineJobQueue


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
