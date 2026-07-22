from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from redis import Redis
from rq import Queue, SimpleWorker, Worker
from label_platform.config import Settings
from label_platform.db.session import create_engine_from_settings, create_session_factory
from label_platform.integrations.labelstudio import create_label_studio_connector
from label_platform.integrations.unitrain import create_unitrain_connector
from label_platform.reconciliation import reconcile_external_state
from label_platform.reviews.service import ReviewWorkflow
from label_platform.training.service import TrainingWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="label-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    worker = subparsers.add_parser("worker", help="Run the dataset operations worker")
    worker.add_argument(
        "--simple",
        action="store_true",
        help="Run jobs in-process (recommended for native macOS development)",
    )
    subparsers.add_parser("reconcile", help="Reconcile active external sessions and runs")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "worker":
        settings = Settings()
        connection = Redis.from_url(settings.redis_url)
        queue = Queue("dataset-operations", connection=connection)
        worker_type = SimpleWorker if args.simple else Worker
        worker_type([queue], connection=connection).work()
        return 0
    if args.command == "reconcile":
        settings = Settings()
        engine = create_engine_from_settings(settings)
        label_studio = create_label_studio_connector(settings)
        unitrain = create_unitrain_connector(settings)
        try:
            session_factory = create_session_factory(engine)
            result = reconcile_external_state(
                session_factory,
                review_workflow=ReviewWorkflow(
                    session_factory,
                    managed_root=settings.managed_data_root,
                    export_root=settings.label_studio_export_root,
                    label_studio_mount_root=settings.label_studio_mount_root,
                    label_studio_base_url=settings.label_studio_public_url,
                    connector=label_studio,
                ),
                training_workflow=TrainingWorkflow(
                    session_factory,
                    managed_root=settings.managed_data_root,
                    export_root=settings.unitrain_export_root,
                    unitrain_mount_root=settings.unitrain_mount_root,
                    connector=unitrain,
                ),
            )
            print(json.dumps(result.__dict__, ensure_ascii=False))
            return 1 if result.errors else 0
        finally:
            label_studio.close()
            unitrain.close()
            engine.dispose()
    return 2
