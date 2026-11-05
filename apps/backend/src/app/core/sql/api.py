from app.core.sql.executor import SQLExecutor

async def sql_execute_safe(*, sql: str, params: dict, tenant_id: str, security_level: int | None = None):
    """
    Executes a SQL query safely using the SQLExecutor with policy enforcement.
    
    Args:
        sql: The raw SQL query (with placeholders).
        params: Dictionary of parameters for the query.
        tenant_id: The tenant ID for row-level security.
        security_level: Optional security level (reserved for future use).
        
    Returns:
        Dict containing "data" (rows) and "meta" (execution info).
    """
    executor = SQLExecutor()
    return await executor.execute_safe(sql=sql, params=params, tenant_id=tenant_id)
