from __future__ import annotations

from pathlib import Path

from app.migrations.apply_migrations import _iter_migration_files, _normalize_conninfo


def test_normalize_conninfo_handles_async_driver_prefix() -> None:
    src = "postgresql+asyncpg://user:pw@db:5432/app"
    out = _normalize_conninfo(src)
    assert out == "postgresql://user:pw@db:5432/app"


def test_iter_migration_files_sorted(tmp_path: Path) -> None:
    (tmp_path / "010_last.sql").write_text("-- x", encoding="utf-8")
    (tmp_path / "002_mid.sql").write_text("-- y", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("-- z", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("ignore", encoding="utf-8")

    files = _iter_migration_files(tmp_path)
    names = [p.name for p in files]
    assert names == ["001_first.sql", "002_mid.sql", "010_last.sql"]


def test_schema_gate_contains_critical_columns() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    migration = repo_root / "apps" / "ingestion" / "migrations" / "005_documents_tenant_soft_delete_baseline.sql"
    sql = migration.read_text(encoding="utf-8").lower()

    assert "add column if not exists tenant_id" in sql
    assert "add column if not exists is_deleted" in sql
    assert "add column if not exists deleted_at" in sql
    assert "add column if not exists meta jsonb" in sql
    assert "idx_documents_tenant_deleted" in sql

