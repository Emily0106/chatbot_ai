# app/tools/sql_validator.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple, Set

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)


class SqlValidationError(ValueError):
    """Loi khi SQL vi pham quy tac an toan."""
    pass


@dataclass
class ValidatedSQL:
    sql: str
    params: Dict[str, Any]
    limit_value: int
    tenant_filter_added: bool


# -----------------------------
# Helpers
# -----------------------------
def _strip_markdown(sql: str) -> str:
    s = (sql or "").strip()
    # Remove ```sql ... ``` fences
    s = re.sub(r"^\s*```sql\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*```\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _is_safe_select(stmt: exp.Expression) -> bool:
    # Allow: SELECT, WITH ... SELECT, and SetOperation (UNION/INTERSECT/EXCEPT)
    if isinstance(stmt, exp.Select):
        return True
    if isinstance(stmt, exp.With) and isinstance(stmt.this, exp.Select):
        return True
    if isinstance(stmt, exp.SetOperation):
        return True
    return False


def _reject_unsafe_nodes(stmt: exp.Expression) -> None:
    """
    Quet AST de chan cac node nguy hiem du nam trong subquery.
    """
    unsafe_types = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Alter,
        exp.Truncate,
        exp.Create,
        exp.Grant,
        exp.Revoke,
    )
    for node in stmt.walk():
        if isinstance(node, unsafe_types):
            raise SqlValidationError(f"Phat hien lenh nguy hiem: {type(node).__name__}")

        if isinstance(node, exp.Table):
            name = (node.name or "").lower()
            if name.startswith("pg_") or "information_schema" in name:
                raise SqlValidationError(f"Cam truy cap bang he thong: {name}")


def _cte_names(stmt: exp.Expression) -> Set[str]:
    """
    Lay danh sach ten CTE (WITH name AS (...))
    """
    names: Set[str] = set()
    with_node = stmt if isinstance(stmt, exp.With) else stmt.args.get("with")
    if not isinstance(with_node, exp.With):
        return names

    for cte in with_node.find_all(exp.CTE):
        alias = cte.alias
        if alias and alias.this:
            names.add(str(alias.this).lower())
    return names


def _enforce_table_whitelist(stmt: exp.Expression, allowed_tables: Optional[Sequence[str]]) -> None:
    if not allowed_tables:
        return

    allow = {t.lower() for t in allowed_tables}
    ctes = _cte_names(stmt)

    for table in stmt.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name:
            continue
        # Cho phep CTE name
        if name in ctes:
            continue
        if name not in allow:
            raise SqlValidationError(f"Bang '{name}' khong nam trong whitelist.")


def _has_tenant_column(where_exp: Optional[exp.Expression], tenant_column: str) -> bool:
    if not where_exp:
        return False
    for col in where_exp.find_all(exp.Column):
        # col.name la ten cot, du co qualify hay khong (t.tenant_id => name=tenant_id)
        if (col.name or "").lower() == tenant_column.lower():
            return True
    return False


def _pick_tenant_qualifier(stmt: exp.Expression) -> Optional[str]:
    """
    Co gang chon qualifier de tranh ambiguous khi JOIN:
    - Neu co 1 bang/alias trong FROM: dung alias do
    - Neu co nhieu bang (JOIN): uu tien bang dau tien trong FROM (alias neu co)
    Return: qualifier (vd "t1") hoac ten bang ("residents"), hoac None
    """
    from_exp = None
    # Với Select: stmt.args.get("from") là exp.From(...)
    # Với SetOperation/With: sẽ find_all Select, lấy select đầu tiên để pick
    if isinstance(stmt, exp.Select):
        from_exp = stmt.args.get("from")
    else:
        first_select = next(stmt.find_all(exp.Select), None)
        if first_select is not None:
            from_exp = first_select.args.get("from")

    if not from_exp:
        return None

    # from_exp.expressions: danh sách nguồn (Table/Join/Subquery...)
    sources = list(getattr(from_exp, "expressions", []) or [])
    if not sources:
        return None

    first = sources[0]

    # Nếu FROM là JOIN node, "this" là bảng trái
    if isinstance(first, exp.Join):
        first = first.this

    # Table
    if isinstance(first, exp.Table):
        if first.alias and first.alias.this:
            return str(first.alias.this)
        return first.name

    # Subquery có alias
    if isinstance(first, exp.Subquery):
        if first.alias and first.alias.this:
            return str(first.alias.this)

    return None


def _add_tenant_filter(
    stmt: exp.Expression,
    tenant_column: str,
    param_name: str,
) -> Tuple[exp.Expression, bool]:
    """
    Them tenant filter an toan.
    Fix ambiguous JOIN:
      - Neu co JOIN/nhieu bang: qualify thanh <qualifier>.tenant_id = :tenant_id
      - Neu khong: tenant_id = :tenant_id

    Luu y: Day la MVP-safe. Neu muon sieu chat, co the ap tenant filter cho tung bang
    (nhung can biet schema de tranh loi cot khong ton tai).
    """
    added = False

    def apply_to_select(sel: exp.Select) -> None:
        nonlocal added

        where_exp = sel.args.get("where")
        if _has_tenant_column(where_exp, tenant_column):
            return

        qualifier = _pick_tenant_qualifier(sel)
        if qualifier:
            condition_sql = f"{qualifier}.{tenant_column} = :{param_name}"
        else:
            condition_sql = f"{tenant_column} = :{param_name}"

        # sqlglot: .where(...) sẽ tự nối AND nếu đã có where
        sel.where(condition_sql, copy=False)
        added = True

    if isinstance(stmt, exp.Select):
        apply_to_select(stmt)
        return stmt, added

    if isinstance(stmt, exp.With):
        # apply trên select chính
        if isinstance(stmt.this, exp.Select):
            apply_to_select(stmt.this)
        return stmt, added

    if isinstance(stmt, exp.SetOperation):
        # Apply trên các vế
        for sel in stmt.find_all(exp.Select):
            apply_to_select(sel)
        return stmt, added

    # Fallback: apply cho mọi SELECT tìm được
    for sel in stmt.find_all(exp.Select):
        apply_to_select(sel)
    return stmt, added


def _extract_limit_value(stmt: exp.Expression) -> Optional[int]:
    limit = stmt.args.get("limit")
    if not limit:
        return None
    val = limit.expression
    if isinstance(val, exp.Literal) and val.is_int:
        return int(val.this)
    return None


def _enforce_limit(stmt: exp.Expression, max_limit: int) -> Tuple[exp.Expression, int]:
    """
    Enforce LIMIT (add/cap).
    Với SetOperation, đặt limit ở node cha là đủ.
    """
    cur = _extract_limit_value(stmt)
    if cur is None:
        stmt.set("limit", exp.Limit(expression=exp.Literal.number(max_limit)))
        return stmt, max_limit

    if cur > max_limit:
        stmt.set("limit", exp.Limit(expression=exp.Literal.number(max_limit)))
        return stmt, max_limit

    return stmt, cur


# -----------------------------
# Public API
# -----------------------------
def validate_and_fix_sql(
    sql: str,
    *,
    tenant_id: str,
    max_limit: int = 100,
    dialect: str = "postgres",
    tenant_column: str = "tenant_id",
    allowed_tables: Optional[Sequence[str]] = None,
    require_tenant_filter: bool = True,
) -> ValidatedSQL:
    """
    Validate + Auto-fix SQL an toan cho Text-to-SQL.

    - Single statement
    - Read-only SELECT / WITH / SetOperation
    - Reject unsafe nodes (write DDL/DML) even nested
    - Block system tables
    - Optional: whitelist tables (CTE names are allowed)
    - Auto add tenant filter with placeholder :tenant_id
      (qualified to avoid ambiguous JOIN)
    - Enforce LIMIT
    """
    clean_sql = _strip_markdown(sql)
    if not clean_sql:
        raise SqlValidationError("SQL rong.")

    try:
        expressions = sqlglot.parse(clean_sql, read=dialect)
    except Exception as e:
        raise SqlValidationError(f"Loi cu phap SQL: {type(e).__name__}") from e

    if len(expressions) != 1:
        raise SqlValidationError("Chi cho phep 1 cau SQL duy nhat (single statement).")

    stmt = expressions[0]

    if not _is_safe_select(stmt):
        raise SqlValidationError("Chi cho phep SELECT/CTE SELECT/UNION (read-only).")

    # Deep scan: block unsafe + system tables
    _reject_unsafe_nodes(stmt)

    # Optional whitelist (skip CTE)
    _enforce_table_whitelist(stmt, allowed_tables)

    params: Dict[str, Any] = {}
    tenant_added = False

    if require_tenant_filter:
        stmt, tenant_added = _add_tenant_filter(stmt, tenant_column, "tenant_id")
        params["tenant_id"] = tenant_id
        if tenant_added:
            logger.info("Auto-fixed SQL: added tenant filter (column=%s) for tenant_id=%s", tenant_column, tenant_id)

    stmt, final_limit = _enforce_limit(stmt, max_limit=max_limit)

    out_sql = stmt.sql(dialect=dialect).strip().rstrip(";")
    return ValidatedSQL(
        sql=out_sql,
        params=params,
        limit_value=final_limit,
        tenant_filter_added=tenant_added,
    )
