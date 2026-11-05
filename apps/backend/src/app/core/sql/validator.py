import re
import json
import hashlib
import datetime
import sqlglot
from sqlglot import exp
from typing import Any, Dict, List, Optional, Tuple, Set
from sqlglot.dialects.postgres import Postgres

from .types import SQLPolicy, SafeSQL, Lane, SecurityError, ValidationError

class CustomPostgres(Postgres):
    class Generator(Postgres.Generator):
        def parameter_sql(self, expression):
            # Force :name syntax for SQLAlchemy
            return f":{expression.name}"

class SQLValidator:
    def validate_and_transform(
        self,
        *,
        raw_sql: str,
        params: Dict[str, Any],
        tenant_id: str,
        policy: SQLPolicy,
        lane: Lane,
    ) -> SafeSQL:
        # 0) Normalize & strip comments BEFORE parse
        sql0 = self._strip_sql_comments(raw_sql)
        sql0 = " ".join(sql0.split()) # collapse whitespace

        # 1) Hard block: multi-statement / suspicious tokens
        if self._looks_like_multi_statement(sql0):
            raise SecurityError("multi_statement_forbidden")

        # 2) Parse AST
        try:
            # read="postgres" ensures we parse using Postgres dialect rules
            parsed_list = sqlglot.parse(sql0, read="postgres")
            if not parsed_list:
                raise ValidationError("empty_sql")
            if len(parsed_list) > 1:
                raise SecurityError("multi_statement_forbidden")
            ast = parsed_list[0]
        except Exception as e:
            if isinstance(e, (SecurityError, ValidationError)):
                raise e
            raise ValidationError(f"sql_parse_failed: {str(e)}")

        # 3) Enforce statement type: SELECT only
        self._check_forbidden_nodes(ast)

        # 4) Forbid set operations if policy requires
        if policy.forbid_set_ops and self._has_node_type(ast, (exp.Union, exp.Intersect, exp.Except)):
            raise SecurityError("set_ops_forbidden")

        # 5) Optional: forbid subquery/join complexity
        if policy.forbid_subquery and self._has_node_type(ast, exp.Subquery):
            raise SecurityError("subquery_forbidden")
        if policy.forbid_join and self._has_node_type(ast, exp.Join):
            raise SecurityError("join_forbidden")
        if policy.max_joins is not None and self._count_joins(ast) > policy.max_joins:
            raise SecurityError("too_many_joins")

        # 6) Whitelist relations (views/tables)
        self._enforce_allowed_relations(ast, policy.allowed_relations)

        # 7) Optional: column whitelist per relation
        if policy.allowed_columns:
            self._enforce_allowed_columns(ast, policy.allowed_columns)

        # 8) Tenant isolation injection
        injected_info = {"tenant_injected": 0, "tenant_replaced": 0, "limit_injected": False}
        
        # Find all SELECT nodes (including subqueries if allowed)
        select_nodes = list(ast.find_all(exp.Select))
        if isinstance(ast, exp.Select) and ast not in select_nodes:
            select_nodes.append(ast)
            
        for sel in select_nodes:
            injected_info = self._enforce_tenant_predicate(
                sel, 
                tenant_col=policy.tenant_column, 
                tenant_id=tenant_id, 
                injected_info=injected_info
            )

        # 9) LIMIT enforcement
        ast, injected_info = self._enforce_limit(ast, max_limit=policy.max_limit, injected_info=injected_info)

        # 10) Params sanitization + inject tenant param
        safe_params = self._sanitize_params(params)
        safe_params["tenant_id_val"] = tenant_id

        # 11) Canonicalize SQL
        # Use standard postgres dialect but fix params for SQLAlchemy
        safe_sql = ast.sql(dialect="postgres")
        
        # Replace %(name)s with :name (SQLAlchemy syntax)
        # sqlglot postgres dialect outputs %(name)s for named parameters
        safe_sql = re.sub(r'%\((\w+)\)s', r':\1', safe_sql)
        
        # Also replace $name with :name (if sqlglot outputs $name)
        # Avoid replacing $1, $2 (digits only) which are positional
        safe_sql = re.sub(r'\$([a-zA-Z_]\w*)', r':\1', safe_sql)
        
        # Fingerprint
        param_schema = {k: type(v).__name__ for k, v in safe_params.items()}
        fp_content = safe_sql + json.dumps(param_schema, sort_keys=True)
        fp = hashlib.sha256(fp_content.encode("utf-8")).hexdigest()

        return SafeSQL(sql=safe_sql, params=safe_params, injected=injected_info, fingerprint=fp)

    def _strip_sql_comments(self, sql: str) -> str:
        # Remove /* ... */
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        # Remove -- ...
        sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
        return sql

    def _looks_like_multi_statement(self, sql: str) -> bool:
        stripped = sql.strip()
        # sqlglot.parse is the real check
        return False

    def _check_forbidden_nodes(self, ast: exp.Expression):
        for node in ast.walk():
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Grant, exp.Revoke, exp.Copy)):
                raise SecurityError("ddl_dml_forbidden")

    def _has_node_type(self, ast: exp.Expression, node_types) -> bool:
        return any(isinstance(node, node_types) for node in ast.walk())

    def _count_joins(self, ast: exp.Expression) -> int:
        return len(list(ast.find_all(exp.Join)))

    def _enforce_allowed_relations(self, ast: exp.Expression, allowed: List[str]):
        for table in ast.find_all(exp.Table):
            name = table.name
            if name not in allowed:
                raise SecurityError(f"relation_not_allowed:{name}")

    def _enforce_allowed_columns(self, ast: exp.Expression, allowed_map: Dict[str, List[str]]):
        for col in ast.find_all(exp.Column):
            tbl = col.table
            col_name = col.name
            if tbl and tbl in allowed_map:
                if col_name not in allowed_map[tbl]:
                    raise SecurityError(f"column_not_allowed:{tbl}.{col_name}")

    def _enforce_tenant_predicate(self, select_exp: exp.Select, tenant_col: str, tenant_id: str, injected_info: Dict[str, Any]) -> Dict[str, Any]:
        # Build predicate: tenant_col = :__tenant_id
        pred = exp.EQ(
            this=exp.Column(this=exp.Identifier(this=tenant_col, quoted=False)),
            expression=exp.Parameter(this=exp.Identifier(this="tenant_id_val", quoted=False))
        )

        where = select_exp.args.get("where")

        if not where:
            select_exp.where(pred, copy=False)
            injected_info["tenant_injected"] += 1
            return injected_info

        # If WHERE exists, just AND it at the top level for safety
        select_exp.where(pred, append=True, copy=False)
        injected_info["tenant_injected"] += 1
        
        return injected_info

    def _enforce_limit(self, ast: exp.Expression, max_limit: int, injected_info: Dict[str, Any]) -> Tuple[exp.Expression, Dict[str, Any]]:
        # Only enforce on the ROOT Select node
        if not isinstance(ast, exp.Select):
            return ast, injected_info

        limit_node = ast.args.get("limit")
        
        if not limit_node:
            # Case 1: No Limit -> Add Limit
            ast.limit(max_limit, copy=False)
            injected_info["limit_injected"] = True
        else:
            # Case 2 & 3: Check existing limit
            try:
                # limit_node is exp.Limit, we need its expression (the value)
                # limit_node.expression might be Literal or something else
                val_exp = limit_node.expression
                if isinstance(val_exp, exp.Literal) and val_exp.is_int:
                    current_val = int(val_exp.this)
                    if current_val > max_limit:
                        # Cap it
                        limit_node.set("expression", exp.Literal.number(max_limit))
                        injected_info["limit_injected"] = True
                else:
                    # If complex expression (e.g. parameter), we might want to force cap or block.
                    # For now, let's force overwrite to be safe if it's not a simple safe int
                    limit_node.set("expression", exp.Literal.number(max_limit))
                    injected_info["limit_injected"] = True
            except Exception:
                # Fallback: overwrite
                limit_node.set("expression", exp.Literal.number(max_limit))
                injected_info["limit_injected"] = True

        return ast, injected_info

    def _sanitize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        safe = {}
        for k, v in params.items():
            # Keep datetime objects for Driver to handle
            if isinstance(v, (str, int, float, bool, type(None), datetime.date, datetime.datetime)):
                safe[k] = v
            else:
                # Convert others to string to be safe
                safe[k] = str(v)
        return safe
