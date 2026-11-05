import asyncio
import json
import os
import random
import logging
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

# Load env
load_dotenv("env/dev.env")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or "postgresql+asyncpg://postgres:password@localhost:5432/app_db"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OUTPUT_FILE = "tests/golden_rag.jsonl"
NUM_CHUNKS_TO_SAMPLE = 20

# Prompts
PROMPT_GENERATE_QA = """
SYSTEM:
Bạn là công cụ tạo dữ liệu kiểm thử (golden set) cho hệ thống RAG của Chính quyền. 
Nguyên tắc tối thượng: TUYỆT ĐỐI KHÔNG BỊA. Chỉ được dùng thông tin có trong đoạn văn bản được cung cấp.

USER:
Bạn sẽ nhận:
- doc_title: tiêu đề văn bản (có thể rỗng)
- doc_type/domain: loại tài liệu (có thể rỗng)
- chunk_text: một đoạn trích từ tài liệu

NHIỆM VỤ:
Tạo 1 cặp (question, ideal_answer) sao cho:
1) Câu hỏi phải CỤ THỂ, rõ ràng, không mơ hồ, có thể trả lời trọn vẹn chỉ bằng chunk_text.
2) Câu trả lời phải NGẮN GỌN (<= 80 từ), trung thực, không suy diễn ngoài chunk_text.
3) Trích xuất 2–4 "must_contain" là các cụm từ/keyword QUAN TRỌNG xuất hiện trực tiếp trong chunk_text (ví dụ: thời hạn, lệ phí, tên thủ tục, cơ quan, mẫu biểu, số điều/khoản, số văn bản...). 
   - must_contain nên là cụm 2–6 từ, copy đúng chính tả như trong chunk_text (không tự bịa).
4) Nếu chunk_text là rác (header/footer, mục lục, tiêu đề đơn lẻ, danh sách trang, câu quá chung chung, chỉ có tên văn bản mà không có nội dung quy định), hoặc không đủ thông tin để tạo câu hỏi cụ thể → hãy trả về SKIP.

RÀNG BUỘC AN TOÀN:
- Không tạo câu hỏi/đáp án liên quan PII (CCCD, số điện thoại, địa chỉ cụ thể, dữ liệu cá nhân).
- Không dùng kiến thức bên ngoài.
- Không trích dẫn dài dòng.

OUTPUT:
Chỉ được trả về JSON HỢP LỆ (không markdown, không giải thích).
Hai dạng output:

(A) Nếu tạo được:
{{
  "skip": false,
  "question": "...",
  "ideal_answer": "...",
  "must_contain": ["...", "...", "..."],
  "answer_style": "fact" | "procedure" | "definition",
  "confidence": 0.0-1.0
}}

(B) Nếu SKIP:
{{
  "skip": true,
  "reason": "header_footer|toc|too_short|too_vague|pii_risk|not_answerable"
}}

INPUT:
doc_title: {doc_title}
doc_type: {doc_type}
domain: {domain}
chunk_text:
\"\"\"
{chunk_text}
\"\"\"
"""

# DB Setup
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def fetch_random_chunks(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch random chunks from the database."""
    async with AsyncSessionLocal() as session:
        # Adjust table/column names if needed. Assuming 'chunks' table.
        # We also join with 'documents' to get title/domain if possible, 
        # but for now let's assume chunks has what we need or we just use chunk content.
        # If chunks table doesn't have doc metadata, we might need a join.
        # Let's try a simple query first.
        try:
            sql = text("""
                SELECT 
                    c.chunk_id, 
                    c.doc_id, 
                    c.display_text as content, 
                    c.doc_category as doc_type, 
                    c.scope as domain,
                    d.title as doc_title
                FROM chunks c
                LEFT JOIN documents d ON c.doc_id = d.doc_id
                ORDER BY RANDOM()
                LIMIT :limit
            """)
            result = await session.execute(sql, {"limit": limit})
            rows = result.mappings().all()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching chunks: {e}")
            return []

async def generate_qa(client: AsyncOpenAI, chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Generate Q&A for a single chunk."""
    content = chunk.get("content") or ""
    if len(content) < 100: # Skip very short chunks immediately
        return None

    prompt = PROMPT_GENERATE_QA.format(
        doc_title=chunk.get("doc_title") or "",
        doc_type=chunk.get("doc_type") or "",
        domain=chunk.get("domain") or "",
        chunk_text=content
    )

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        content_str = response.choices[0].message.content
        if not content_str:
            return None
            
        data = json.loads(content_str)
        
        if data.get("skip"):
            logger.info(f"Skipped chunk {chunk.get('chunk_id')}: {data.get('reason')}")
            return None
            
        # Enrich with chunk info
        data["expected_chunk_id"] = str(chunk.get("chunk_id"))
        data["expected_document_id"] = str(chunk.get("doc_id"))
        data["tags"] = ["rag", "auto", data.get("answer_style", "general")]
        
        # Remove internal fields
        data.pop("skip", None)
        data.pop("reason", None)
        
        return data

    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return None

async def main():
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not set. Please set it to run this script.")
        return

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    logger.info("Fetching random chunks...")
    chunks = await fetch_random_chunks(NUM_CHUNKS_TO_SAMPLE)
    logger.info(f"Fetched {len(chunks)} chunks.")

    golden_data = []
    
    # Process sequentially to avoid rate limits (or use semaphore for concurrency)
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {i+1}/{len(chunks)}...")
        qa = await generate_qa(client, chunk)
        if qa:
            # Add an ID
            qa["id"] = f"rag_auto_{i+1:04d}"
            golden_data.append(qa)
            logger.info(f"Generated QA: {qa['question']}")

    # Save to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for item in golden_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    logger.info(f"Saved {len(golden_data)} QA pairs to {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
