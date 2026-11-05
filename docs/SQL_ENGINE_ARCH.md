# Gov-AI SQL Engine Architecture

## Overview
The **Gov-AI SQL Engine** is a secure, AI-powered system designed to translate natural language queries into safe, optimized SQL for the GovTech platform. It replaces legacy heuristic lookups with a dynamic Text-to-SQL generation pipeline.

## Core Components

### 1. SQLGenerator (`app/core/sql/generator.py`)
*   **Role:** The "Brain". Translates user questions into SQL.
*   **Model:** Uses `gpt-4o-mini` (configurable via `SQL_LLM_MODEL`).
*   **Context:** Loads schema definitions and domain dictionary from `docs/schema_context.md`.
*   **Safety:** Enforces strict JSON output and parameterized queries.

### 2. SQLValidator (`app/core/sql/validator.py`)
*   **Role:** The "Gatekeeper". Validates generated SQL against security policies.
*   **Features:**
    *   **AST Parsing:** Uses `sqlglot` to parse and analyze SQL structure.
    *   **Policy Enforcement:** Checks allowed tables, columns, and forbids DDL/DML.
    *   **Tenant Isolation:** Automatically injects `commune_id = :tenant_id` into queries.
    *   **Limit Enforcement:** Enforces a hard `LIMIT` (default 50) to prevent DoS.
    *   **Parameter Binding:** Ensures compatibility between `sqlglot` and `SQLAlchemy`.

### 3. SQLExecutor (`app/core/sql/executor.py`)
*   **Role:** The "Muscle". Executes validated SQL against the database.
*   **Features:**
    *   **Safe Execution:** Uses `SQLAlchemy` async session.
    *   **Timeouts:** Sets statement timeouts (default 2000ms).
    *   **Logging:** Logs execution time, row count, and SQL fingerprint.

### 4. AccuratePeopleAgent (`app/agents/accurate_people.py`)
*   **Role:** The "Orchestrator". Integrates the SQL Engine into the chat flow.
*   **Flow:**
    1.  **Parse Intent:** Determines if the query is a lookup or general question.
    2.  **Generate:** Calls `SQLGenerator.generate()`.
    3.  **Execute:** Calls `SQLExecutor.execute_safe()`.
    4.  **Fallback:** Handles general SQL queries that don't match specific intents.

## Data Flow

1.  **User Query:** "Thống kê tổng thu ngân sách năm 2024"
2.  **Agent:** Detects intent or routes to general SQL fallback.
3.  **Generator:**
    *   Input: Query + Schema Context
    *   Output: `SELECT SUM(amount) FROM view_budget WHERE year = :year ...` + Params: `{"year": 2024}`
4.  **Validator:**
    *   Input: Raw SQL + Params + Tenant ID
    *   Check: Allowed tables (`view_budget`), No DDL.
    *   Transform: Inject `commune_id = :tenant_id`, Enforce `LIMIT`.
    *   Output: Safe SQL Object.
5.  **Executor:**
    *   Run: `await session.execute(safe_sql, params)`
    *   Result: `[{"sum": 15000000000}]`
6.  **Agent:** Formats result and responds to user.

## How to Add New Tables

1.  **Update Schema Context:**
    *   Edit `docs/schema_context.md`.
    *   Add the new table/view definition (columns, types, description).
    *   Add domain dictionary mapping for new terms.
    *   Add sample queries.

2.  **Update SQL Policy:**
    *   Edit `app/core/sql/executor.py` (or `config.py` if externalized).
    *   Add the new table name to `allowed_relations` in `SQLPolicy`.

3.  **Restart Backend:**
    *   `docker restart compose-backend-1` to reload the schema context and policy.
