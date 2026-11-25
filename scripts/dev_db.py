"""Start a local PostgreSQL server for development.

The embedded PostgreSQL distribution from the optional ``testing`` extra
(``pgserver``) is used, so no system-wide PostgreSQL service or Docker is
required. Data persists in ``.pgdata/`` between runs; Ctrl+C stops the server
without deleting it.

The server listens on the loopback interface (``127.0.0.1`` and ``::1``) on a
fixed port (5432 by default) so the default ``SYNTRA_DATABASE_URL`` and saved
GUI connection profiles keep working across restarts.

Usage (PowerShell):

    .venv\\Scripts\\python.exe scripts\\dev_db.py
    .venv\\Scripts\\python.exe scripts\\dev_db.py --migrate
    .venv\\Scripts\\python.exe scripts\\dev_db.py --port 5433
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

PGDATA = PROJECT_ROOT / ".pgdata"
DATABASE_NAME = "syntra"
DEFAULT_HOST = "127.0.0.1"
# Bind both loopback addresses: libpq resolves ``localhost`` to ``::1`` first and
# hangs until its connect timeout if only IPv4 is listening.
DEFAULT_LISTEN = "127.0.0.1,::1"
DEFAULT_PORT = 5432


def build_url(host: str, port: int, database: str) -> str:
    """Return an SQLAlchemy URL that uses the psycopg 3 driver."""
    url = make_url(f"postgresql://postgres@{host}:{port}/{database}")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) != 0


def ensure_database(admin_url: str) -> None:
    """Create the application database if it does not exist yet."""
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": DATABASE_NAME},
            ).scalar()
            if exists:
                print(f'database "{DATABASE_NAME}" already exists')
                return
            connection.execute(text(f'CREATE DATABASE "{DATABASE_NAME}"'))
            print(f'created database "{DATABASE_NAME}"')
    finally:
        engine.dispose()


def run_migrations(db_url: str) -> None:
    """Apply every Alembic migration against the development database."""
    from alembic import command
    from alembic.config import Config

    os.environ["SYNTRA_DATABASE_URL"] = db_url
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.upgrade(config, "head")


def running_port(pgdata: Path, PostmasterInfo: type) -> int | None:
    """Return the port of a server already running on ``pgdata``, if any."""
    info = PostmasterInfo.read_from_pgdata(pgdata)
    if info is not None and info.is_running():
        return info.port
    return None


def start_server(listen: str, port: int, log_file: Path) -> None:
    """Start the cluster and wait until it accepts connections.

    ``pg_ctl -l`` is deliberately not used: on Windows the startup process
    reopens the log file while the postmaster still holds it, which fails with
    a sharing violation whenever the cluster needs crash recovery.  Redirecting
    the child's standard streams instead lets every process inherit one handle.
    """
    from pgserver._commands import POSTGRES_BIN_PATH

    pg_ctl = POSTGRES_BIN_PATH / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
    command = [
        str(pg_ctl),
        "-D",
        str(PGDATA),
        "-w",
        "-o",
        f'-h "{listen}"',
        "-o",
        f"-p {port}",
        "start",
    ]
    with log_file.open("a", encoding="utf-8", errors="replace") as log:
        subprocess.run(
            command,
            check=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=60,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="apply Alembic migrations before serving",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"address to report for connections (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--listen",
        default=DEFAULT_LISTEN,
        help=f"comma-separated interfaces to listen on (default: {DEFAULT_LISTEN})",
    )
    args = parser.parse_args()

    try:
        import pgserver
        from pgserver.utils import PostmasterInfo
    except ImportError:
        print(
            'pgserver is not installed; run: pip install -e ".[testing]"',
            file=sys.stderr,
        )
        return 1

    PGDATA.mkdir(parents=True, exist_ok=True)
    log_file = PGDATA / "postmaster.log"

    existing_port = running_port(PGDATA, PostmasterInfo)
    if existing_port is not None:
        if existing_port != args.port:
            print(
                f"a server is already running on {PGDATA} at port {existing_port}; "
                "reusing it (stop it first to change the port)",
                file=sys.stderr,
            )
        args.port = existing_port
    else:
        # A crashed server can leave a stale pid file behind, which blocks startup.
        stale_pid = PGDATA / "postmaster.pid"
        if stale_pid.exists():
            stale_pid.unlink()

        if not (PGDATA / "PG_VERSION").exists():
            print(f"initialising a new cluster in {PGDATA} ...")
            pgserver.initdb(
                ["--auth=trust", "--auth-local=trust", "--encoding=utf8", "-U", "postgres"],
                pgdata=PGDATA,
            )

        if not port_is_free(args.host, args.port):
            print(
                f"port {args.port} on {args.host} is already in use; "
                "stop the other server or pass --port",
                file=sys.stderr,
            )
            return 1

        try:
            start_server(args.listen, args.port, log_file)
        except Exception:
            print(f"PostgreSQL failed to start; see {log_file}", file=sys.stderr)
            if log_file.exists():
                print(log_file.read_text(encoding="utf-8", errors="replace")[-4000:])
            return 1

    db_url = build_url(args.host, args.port, DATABASE_NAME)
    admin_url = build_url(args.host, args.port, "postgres")

    try:
        ensure_database(admin_url)
        if args.migrate:
            run_migrations(db_url)
            print("migrations applied (alembic upgrade head)")

        print()
        print(f"PostgreSQL is running on {args.host}:{args.port} (data: {PGDATA})")
        print(f"SYNTRA_DATABASE_URL={db_url}")
        print()
        print("PowerShell:")
        print(f'  $env:SYNTRA_DATABASE_URL = "{db_url}"')
        print()
        print("Press Ctrl+C to stop the server (the data directory is kept).", flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping PostgreSQL...")
    finally:
        if running_port(PGDATA, PostmasterInfo) is not None:
            pgserver.pg_ctl(["-w", "stop"], pgdata=PGDATA, timeout=30)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
