from __future__ import annotations

import argparse
import hashlib
import os
import time
from pathlib import Path
from typing import Iterable, List

import psycopg

from app.core.config import settings

TRACKING_TABLE = "ingestion_schema_migrations"


def _normalize_conninfo(conninfo: str) -> str:
    value = str(conninfo or "").strip()
    if value.startswith("postgresql+asyncpg://"):
        return "postgresql://" + value[len("postgresql+asyncpg://") :]
    if value.startswith("postgresql+psycopg://"):
        return "postgresql://" + value[len("postgresql+psycopg://") :]
    return value


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _iter_migration_files(migrations_dir: Path) -> List[Path]:
    return sorted([p for p in migrations_dir.glob("*.sql") if p.is_file()], key=lambda p: p.name)


def _wait_for_db(conninfo: str, timeout_s: int, poll_s: float) -> None:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        try:
            with psycopg.connect(conninfo):
                return
        except Exception as exc:
            last_error = str(exc)
            time.sleep(poll_s)
    raise RuntimeError(f"Database is not reachable within {timeout_s}s: {last_error}")


def _ensure_tracking_table(conninfo: str) -> None:
    sql = f"""
    CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
      filename TEXT PRIMARY KEY,
      checksum TEXT NOT NULL,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def _is_applied(cur: psycopg.Cursor, filename: str, checksum: str) -> bool:
    cur.execute(
        f"SELECT checksum FROM {TRACKING_TABLE} WHERE filename = %s",
        (filename,),
    )
    row = cur.fetchone()
    if not row:
        return False
    existing = str(row[0])
    if existing != checksum:
        raise RuntimeError(
            f"Migration checksum mismatch for {filename}: existing={existing} new={checksum}. "
            "Refusing to continue."
        )
    return True


def _apply_one(conninfo: str, path: Path) -> None:
    sql_text = path.read_text(encoding="utf-8")
    checksum = _sha256_text(sql_text)
    filename = path.name

    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            if _is_applied(cur, filename, checksum):
                print(f"[migrate] skip {filename} (already applied)")
                return
            print(f"[migrate] apply {filename}")
            cur.execute(sql_text)
            cur.execute(
                f"INSERT INTO {TRACKING_TABLE} (filename, checksum) VALUES (%s, %s)",
                (filename, checksum),
            )
        conn.commit()


def apply_all(*, conninfo: str, migrations_dir: Path) -> None:
    files = _iter_migration_files(migrations_dir)
    if not files:
        raise RuntimeError(f"No migration files found in {migrations_dir}")

    _ensure_tracking_table(conninfo)
    for path in files:
        _apply_one(conninfo, path)
    print(f"[migrate] done ({len(files)} files scanned)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply ingestion SQL migrations")
    parser.add_argument(
        "--migrations-dir",
        default=os.getenv("INGEST_MIGRATIONS_DIR", "/app/migrations"),
        help="Directory containing *.sql migration files",
    )
    parser.add_argument(
        "--database-url",
        default=str(getattr(settings, "DATABASE_URL", "") or ""),
        help="Postgres connection string",
    )
    parser.add_argument("--wait-timeout-s", type=int, default=120)
    parser.add_argument("--poll-interval-s", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conninfo = _normalize_conninfo(args.database_url)
    if not conninfo:
        raise RuntimeError("DATABASE_URL is required")

    migrations_dir = Path(args.migrations_dir).resolve()
    if not migrations_dir.exists():
        raise RuntimeError(f"Migrations directory does not exist: {migrations_dir}")

    _wait_for_db(conninfo, timeout_s=int(args.wait_timeout_s), poll_s=float(args.poll_interval_s))
    apply_all(conninfo=conninfo, migrations_dir=migrations_dir)


if __name__ == "__main__":
    main()

