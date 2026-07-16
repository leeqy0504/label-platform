from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Sequence

from redis import Redis
from rq import Queue, Worker
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from label_platform.auth.passwords import hash_password
from label_platform.config import Settings
from label_platform.db.models import User
from label_platform.db.session import create_engine_from_settings, create_session_factory
from label_platform.domain.enums import UserRole
from label_platform.integrations.labelstudio import create_label_studio_connector
from label_platform.integrations.unitrain import create_unitrain_connector
from label_platform.reconciliation import reconcile_external_state
from label_platform.reviews.service import ReviewWorkflow
from label_platform.training.service import TrainingWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="label-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_admin = subparsers.add_parser("create-admin", help="Create an administrator")
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--name", required=True)
    subparsers.add_parser("worker", help="Run the dataset operations worker")
    subparsers.add_parser("reconcile", help="Reconcile active external sessions and runs")
    return parser


def create_admin(email: str, name: str, settings: Settings) -> int:
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match", file=sys.stderr)
        return 2
    if len(password) < 8:
        print("Password must contain at least 8 characters", file=sys.stderr)
        return 2

    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    normalized_email = email.strip().lower()
    try:
        with session_factory() as session:
            if session.scalar(select(User).where(User.email == normalized_email)) is not None:
                print("A user with this email already exists", file=sys.stderr)
                return 2
            user = User(
                email=normalized_email,
                name=name.strip(),
                password_hash=hash_password(password),
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(user)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                print("A user with this email already exists", file=sys.stderr)
                return 2
    finally:
        engine.dispose()

    print(f"Created administrator {normalized_email}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.name, Settings())
    if args.command == "worker":
        settings = Settings()
        connection = Redis.from_url(settings.redis_url)
        queue = Queue("dataset-operations", connection=connection)
        Worker([queue], connection=connection).work()
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
                    label_studio_base_url=settings.label_studio_url,
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
