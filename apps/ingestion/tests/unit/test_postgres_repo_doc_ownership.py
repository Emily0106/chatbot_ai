from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.preproc.stores.postgres_repo import PostgresRepo


class _FakeCursor:
    def __init__(self, *, fetchone_result: Optional[Dict[str, Any]] = None, rowcount: int = 0) -> None:
        self.fetchone_result = fetchone_result
        self.rowcount = rowcount
        self.executed: List[Tuple[str, Tuple[Any, ...] | None]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: Tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.fetchone_result


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits = 0

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self, *args, **kwargs) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1


def _build_repo(*, fetchone_result: Optional[Dict[str, Any]] = None, rowcount: int = 0):
    repo = object.__new__(PostgresRepo)
    cursor = _FakeCursor(fetchone_result=fetchone_result, rowcount=rowcount)
    conn = _FakeConn(cursor)
    repo._conn = lambda: conn  # type: ignore[method-assign]
    return repo, cursor, conn


def test_get_document_for_tenant_adds_tenant_and_not_deleted_filter() -> None:
    repo, cursor, _ = _build_repo(fetchone_result={"doc_id": "d1"})

    row = repo.get_document_for_tenant("d1", "tenant-a")

    assert row == {"doc_id": "d1"}
    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert "doc_id = %s" in sql
    assert "tenant_id = %s" in sql
    assert "is_deleted = FALSE" in sql
    assert params == ("d1", "tenant-a")


def test_get_document_for_tenant_include_deleted_skips_is_deleted_filter() -> None:
    repo, cursor, _ = _build_repo(fetchone_result={"doc_id": "d2"})

    row = repo.get_document_for_tenant("d2", "tenant-b", include_deleted=True)

    assert row == {"doc_id": "d2"}
    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert "doc_id = %s" in sql
    assert "tenant_id = %s" in sql
    assert "is_deleted = FALSE" not in sql
    assert params == ("d2", "tenant-b")


def test_soft_delete_document_for_tenant_returns_rowcount_and_commits() -> None:
    repo, cursor, conn = _build_repo(rowcount=1)

    affected = repo.soft_delete_document_for_tenant("d3", "tenant-c")

    assert affected == 1
    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert "UPDATE documents" in sql
    assert "tenant_id = %s" in sql
    assert "is_deleted = FALSE" in sql
    assert params == ("d3", "tenant-c")
    assert conn.commits == 1


def test_delete_chunks_rows_for_doc_deletes_rows_and_chunks() -> None:
    repo, cursor, conn = _build_repo()

    repo.delete_chunks_rows_for_doc("d4")

    assert len(cursor.executed) == 2
    first_sql, first_params = cursor.executed[0]
    second_sql, second_params = cursor.executed[1]
    assert "DELETE FROM structured_rows" in first_sql
    assert "DELETE FROM chunks" in second_sql
    assert first_params == ("d4",)
    assert second_params == ("d4",)
    assert conn.commits == 1
