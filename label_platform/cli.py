from __future__ import annotations

import argparse
import getpass
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="label-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_admin = subparsers.add_parser("create-admin", help="Create an administrator")
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--name", required=True)
    subparsers.add_parser("worker", help="Run the dataset operations worker")
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
    return 2
