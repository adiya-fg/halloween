"""Command-line administration.

    python -m app.cli init-db
    python -m app.cli create-admin --username alice          # prompts for password
    echo "$PW" | python -m app.cli create-admin --username alice --password-stdin
    python -m app.cli purge [--days 180]
"""
from __future__ import annotations

import argparse
import getpass
import sys

from .config import Settings
from .services import App, ServiceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create database tables and seed payment settings")
    ca = sub.add_parser("create-admin", help="Create an administrator account")
    ca.add_argument("--username", required=True)
    ca.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")
    pg = sub.add_parser("purge", help="Apply the data-retention policy")
    pg.add_argument("--days", type=int, default=None, help="Defaults to RETENTION_DAYS")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    svc = App(settings)  # creates schema idempotently

    if args.command == "init-db":
        print(f"Database ready at {settings.database_path}")
        return 0

    if args.command == "create-admin":
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass("New admin password (min 12 chars): ")
            if password != getpass.getpass("Repeat password: "):
                print("Passwords do not match.", file=sys.stderr)
                return 1
        try:
            admin_id = svc.create_admin(args.username, password)
        except ServiceError as e:
            print(f"Error: {e.message}", file=sys.stderr)
            return 1
        print(f"Admin '{args.username}' created (id {admin_id}).")
        return 0

    if args.command == "purge":
        days = args.days if args.days is not None else settings.retention_days
        print(svc.purge(days))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
