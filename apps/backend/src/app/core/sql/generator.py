import json
import logging
import os
from typing import Any, Dict, Optional

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

class GenerationError(Exception):
    pass

class SQLGenerator:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            timeout=settings.OPENAI_TIMEOUT,
            max_retries=settings.OPENAI_MAX_RETRIES,
        )
        self.model = settings.SQL_LLM_MODEL
        self.schema_context = self._load_schema_context()

    def _load_schema_context(self) -> str:
        """Loads schema context from docs/schema_context.md"""
        try:
            # Assuming docs is at project root, relative to this file?
            # Better to use absolute path or relative to project root.
            # Current file: apps/backend/src/app/core/sql/generator.py
            # Project root: ../../../../../..
            # Let's try to find it relative to CWD (usually project root in docker)
            path = "docs/schema_context.md"
            if not os.path.exists(path):
                # Fallback for local dev if CWD is different
                path = os.path.join(os.getcwd(), "docs/schema_context.md")
            
            if not os.path.exists(path):
                logger.warning(f"Schema context file not found at {path}")
                return "Schema context not available."

            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load schema context: {e}")
            return "Schema context load failed."

    async def generate(self, user_query: str) -> Dict[str, Any]:
        """
        Generates SQL plan from user query using LLM.
        Returns: { "sql": ..., "params": ..., "thought": ... }
        """
        system_prompt = f"""ROLE: You are a PostgreSQL expert for a GovTech system.
Nhiệm vụ: Chuyển câu hỏi tiếng Việt thành SQL Query an toàn.

CONTEXT (Schema & Dictionary):
{self.schema_context}

CRITICAL RULES:
1. STRICTLY use tables defined in SCHEMA CONTEXT (e.g., "view_people", "view_budget").
2. DO NOT hallucinate table names like "people", "users", "teachers".
3. Use Parameterized Queries (e.g. WHERE name = :name).
4. KHÔNG BAO GIỜ trả về Markdown (```sql). Chỉ trả về JSON thuần.

FEW-SHOT EXAMPLES (Follow this pattern):
User: Tìm cán bộ tên là Nguyễn Văn A
SQL: SELECT * FROM view_people WHERE full_name ILIKE :name LIMIT 20
Params: {{"name": "%Nguyễn Văn A%"}}

User: Số điện thoại của bà Trần Thị B
SQL: SELECT full_name, phone FROM view_people WHERE full_name ILIKE :name LIMIT 20
Params: {{"name": "%Trần Thị B%"}}

User: Tổng thu ngân sách năm 2024
SQL: SELECT SUM(amount) FROM view_budget WHERE year = :year AND item ILIKE '%Thu%'
Params: {{"year": 2024}}

User: Danh sách giáo viên ở Thôn 1
SQL: SELECT * FROM view_people WHERE occupation ILIKE '%Giáo viên%' AND address ILIKE '%Thôn 1%' LIMIT 50
Params: {{}}

OUTPUT FORMAT:
{{
  "thought": "Giải thích ngắn gọn logic mapping cột...",
  "sql": "Câu lệnh SQL chuẩn Postgres...",
  "params": {{ "key": "value" }}
}}
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                response_format={"type": "json_object"},
                temperature=0.0, # Deterministic
            )
            
            content = response.choices[0].message.content
            if not content:
                raise GenerationError("Empty response from LLM")

            result = json.loads(content)
            
            # Basic validation
            if "sql" not in result:
                raise GenerationError("Missing 'sql' field in LLM response")
            
            return result

        except json.JSONDecodeError:
            logger.error("Failed to parse JSON from LLM response")
            raise GenerationError("Invalid JSON response from LLM")
        except Exception as e:
            logger.error(f"LLM Generation failed: {e}")
            raise GenerationError(f"Generation failed: {str(e)}")
