"""
scripts/seed_agent_cert_e2e.py

Certification Data Seeder (V2).
Inserts minimal documents with REAL embeddings into Qdrant + Postgres to support E2E tests.

Requires:
- Local Postgres/Qdrant/Redis (docker compose up -d)
- app.core.llm.embedding (sentence-transformers)
- app.core.db_sql (Postgres connection)
"""
import asyncio
import uuid
import os
import sys
from typing import List, Dict, Any

# Ensure project path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "apps/backend/src"))

from app.core.db_vector import qdrant_client
from app.core.llm.embedding import embed_texts
from app.config import settings
from qdrant_client import models
from sqlalchemy import text

TENANT_ID = "qa_cert_tenant"
COLLECTION_NAME = getattr(settings, "QDRANT_COLLECTION", None) or "gov_knowledge"

DATA_MAP = [
    {
        "doc_type": "law",
        "content": "Luật Công chứng 2024 quy định quy trình công chứng trực tuyến và xác thực sinh trắc học...",
        "meta": {"title": "Luật Công chứng 2024", "security_level": 1, "domain": "justice"}
    },
    {
        "doc_type": "admin_procedure",
        "content": "Thủ tục cấp đổi thẻ căn cước tại Công an cấp xã cần chuẩn bị hồ sơ gồm...",
        "meta": {"title": "Quy trình cấp thẻ Căn cước", "security_level": 1, "domain": "admin"}
    },
    {
        "doc_type": "internal_report",
        "content": "Báo cáo kinh tế quý 3/2025 cho thấy GDP tăng trưởng 6.5%, lạm phát 3%...",
        "meta": {"title": "Báo cáo KT-XH Q3/2025", "security_level": 2, "domain": "economy"}
    },
    {
        "doc_type": "stats",
        "content": "Số liệu thống kê hộ nghèo năm 2024 tại huyện X là 150 hộ, giảm 10%...",
        "meta": {"title": "Thống kê Hộ nghèo 2024", "security_level": 2, "domain": "economy"}
    },
    {
        "doc_type": "health_guidelines",
        "content": "Hướng dẫn điều trị sốt xuất huyết Dengue theo phác đồ Bộ Y tế 2024...",
        "meta": {"title": "Phác đồ Sốt xuất huyết", "security_level": 1, "domain": "health"}
    },
    {
        "doc_type": "culture_guide",
        "content": "Lễ hội Chùa Hương diễn ra từ tháng 1 đến tháng 3 âm lịch tại Mỹ Đức...",
        "meta": {"title": "Lễ hội Chùa Hương", "security_level": 1, "domain": "culture"}
    },
    {
        "doc_type": "tourism_spots",
        "content": "Vịnh Hạ Long là di sản thiên nhiên thế giới với hàng nghìn đảo đá vôi...",
        "meta": {"title": "Vịnh Hạ Long", "security_level": 1, "domain": "tourism"}
    },
    {
        "doc_type": "agri_tech",
        "content": "Kỹ thuật canh tác lúa năng suất cao sử dụng giống ST25 chịu mặn...",
        "meta": {"title": "Kỹ thuật lúa ST25", "security_level": 1, "domain": "agriculture"}
    },
    {
        "doc_type": "meeting_minutes",
        "content": "Biên bản cuộc họp giao ban tuần 40: thống nhất triển khai dự án chuyển đổi số...",
        "meta": {"title": "Giao ban Tuần 40", "security_level": 2, "domain": "internal", "department_id": "dept_IT"}
    },
    {
        "doc_type": "official_document",
        "content": "Công văn 55/UBND chỉ đạo về việc phòng chống bão số 3...",
        "meta": {"title": "CV 55/UBND", "security_level": 2, "domain": "admin", "department_id": "dept_IT"}
    },
    {
        "doc_type": "land_planning",
        "content": "Quy hoạch phân khu đô thị H1-2 xác định khu vực X là đất ở đô thị mật độ cao...",
        "meta": {"title": "Quy hoạch H1-2", "security_level": 2, "domain": "land", "geo_code": "geo_VN"}
    },
    {
        "doc_type": "social_policy",
        "content": "Chính sách trợ cấp xã hội hàng tháng cho người cao tuổi từ 80 tuổi trở lên...",
        "meta": {"title": "Trợ cấp người cao tuổi", "security_level": 2, "domain": "social", "department_id": "dept_social"}
    }
]

async def seed():
    print(">>> Connecting to Qdrant & Postgres...")
    client = qdrant_client
    
    # Generate Embeddings
    print(">>> Generating Embeddings...")
    texts = [item["content"] for item in DATA_MAP]
    vectors = await embed_texts(texts)
    
    points = []
    
    # Prepare Insert Data (Chunks & Docs)
    # We will need to insert into Postgres
    
    from app.core.db_sql import get_async_db
    
    print(f">>> Processing {len(DATA_MAP)} items...")
    
    async for session in get_async_db():
      async with session.begin():
        for i, item in enumerate(DATA_MAP):
            vector = vectors[i]
            meta = item["meta"]
            
            chunk_id = str(uuid.uuid4())
            doc_id = str(uuid.uuid4())
            file_url = f"file://data/{item['doc_type']}_{i}.pdf"
            
            # --- QDRANT PAYLOAD ---
            payload = {
                "doc_type": item["doc_type"],
                "content": item["content"],
                "title": meta["title"],
                "tenant_id": TENANT_ID,
                "security_level": meta["security_level"],
                "domain": meta["domain"],
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "source_uri": file_url, 
                "file_url": file_url
            }
            if "department_id" in meta:
                payload["department_id"] = meta["department_id"]
            if "geo_code" in meta:
                payload["geo_code"] = meta["geo_code"]
                
            points.append(models.PointStruct(
                id=chunk_id, # Use same ID for Point and Chunk for lookup
                vector=vector,
                payload=payload
            ))
            
            # --- POSTGRES INSERT ---
            # 1. Document
            # Schema: doc_id, title, source_uri, scope, (doc_category?), created_at
            scope_val = "public" if meta.get("security_level", 1) == 1 else "internal"
            
            sql_doc = text("""
                INSERT INTO documents (doc_id, title, source_uri, scope, created_at) 
                VALUES (:doc_id, :title, :source_uri, :scope, NOW())
                ON CONFLICT (doc_id) DO NOTHING
            """)
            await session.execute(sql_doc, {
                "doc_id": doc_id,
                "title": meta["title"],
                "source_uri": file_url,
                "scope": scope_val
            })
            
            # 2. Chunk
            # Schema: chunk_id, doc_id, scope, display_text, embed_text, citation (jsonb), commune_id
            sql_chunk = text("""
                INSERT INTO chunks (chunk_id, doc_id, scope, display_text, embed_text, commune_id, citation, created_at)
                VALUES (:chunk_id, :doc_id, :scope, :display_text, :embed_text, :commune_id, :citation, NOW())
                ON CONFLICT (chunk_id) DO NOTHING
            """)
            
            import json
            citation_json = json.dumps({"title": meta["title"]})
            
            await session.execute(sql_chunk, {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "scope": scope_val,
                "display_text": item["content"],
                "embed_text": item["content"],
                "commune_id": TENANT_ID,
                "citation": citation_json
            })
            
        print(f">>> UPSERT QDRANT ({len(points)} pts)...")
        await client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
      break # Use one session

    print(">>> Seed Complete (SQL + Vector).")

if __name__ == "__main__":
    if "--force" not in sys.argv:
        print("NOTE: Run with --force. REAL EMBEDDINGS mode.")
        exit(0)
    asyncio.run(seed())
