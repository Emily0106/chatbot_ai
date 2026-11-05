"""
scripts/seed_qa_data.py

Generates minimal synthetic data for QA testing of the 11 scaffolded agents.
Inserts directly into Qdrant/Postgres if available, or just prints what it would do 
if run in --dry-run mode (default for CI safety).

Usage:
  python scripts/seed_qa_data.py --force
"""
import asyncio
import uuid
import os
import json
from datetime import datetime

# Mock / Project Imports
# We try to import project wrappers. If failing, we fallback to dummy print for safety.
try:
    from app.core.db_vector import get_qdrant_client
    from qdrant_client import models
    from app.core.config import settings
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

REQUIRED_DOC_TYPES = [
    "law", "admin_procedure", "citizen_guide", 
    "internal_report", "stats",
    "health_guidelines", "disease_info",
    "culture_guide", "tourism_spots",
    "agri_tech",
    "meeting_minutes",
    "official_document",
    "land_planning", "construction_permit",
    "social_policy"
]

SAMPLE_TEXTS = {
    "law": "Luật Công chứng 2024 quy định về quy trình công chứng...",
    "admin_procedure": "Thủ tục cấp lại thẻ căn cước công dân gắn chip cần 3 bước...",
    "citizen_guide": "Hướng dẫn nộp phạt vi phạm giao thông trực tuyến...",
    "internal_report": "Báo cáo quý 3/2025 cho thấy tăng trưởng 5%...",
    "stats": "Thống kê dân số xã X năm 2024 là 15,000 người...",
    "health_guidelines": "Hướng dẫn phòng chống sốt xuất huyết tại hộ gia đình...",
    "disease_info": "Triệu chứng bệnh tay chân miệng ở trẻ em...",
    "culture_guide": "Lễ hội chùa Hương diễn ra vào tháng Giêng...",
    "tourism_spots": "Danh thắng Tràng An là di sản văn hóa thế giới...",
    "agri_tech": "Kỹ thuật trồng lúa nước năng suất cao sử dụng giống ST25...",
    "meeting_minutes": "Biên bản họp giao ban tuần 45 kết luận về dự án A...",
    "official_document": "Công văn 123/UBND về việc triển khai chuyển đổi số...",
    "land_planning": "Quy hoạch phân khu đô thị sông Hồng đoạn qua xã X...",
    "construction_permit": "Giấy phép xây dựng số 55/GPXD cho công trình nhà ở...",
    "social_policy": "Chính sách hỗ trợ người có công với cách mạng năm 2025..."
}

async def seed_vectors():
    if not HAS_DEPS:
        print("[WARN] Dependencies missing. Skipping generic DB insert.")
        return

    client = await get_qdrant_client()
    collection_name = settings.QDRANT_COLLECTION_NAME
    
    points = []
    print(f"[INFO] Seeding {len(REQUIRED_DOC_TYPES)} docs into {collection_name}...")
    
    for dt in REQUIRED_DOC_TYPES:
        content = SAMPLE_TEXTS.get(dt, f"No content for {dt}")
        
        # Fake Vector (dim=768 or whatever project uses, using 768 as safe default or 1536)
        # We'll just put zeros for mock if actual embedding model isn't called
        # Ideally we call the embedding service.
        vector = [0.1] * 768 
        
        payload = {
            "doc_type": dt,
            "content": content,
            "title": f"Document for {dt}",
            "tenant_id": "qt_test_tenant", # generic tenant
            "security_level": 1 if "internal" not in dt and "official" not in dt and "land" not in dt and "social" not in dt else 2
        }
        
        points.append(models.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=payload
        ))

    # Upsert
    try:
        await client.upsert(
            collection_name=collection_name,
            points=points
        )
        print("[SUCCESS] Seeding complete.")
    except Exception as e:
        print(f"[ERROR] Failed to seed Qdrant: {e}")

if __name__ == "__main__":
    import sys
    if "--force" in sys.argv:
        asyncio.run(seed_vectors())
    else:
        print("[INFO] DRY RUN. Use --force to actually write to DB.")
        for dt, txt in SAMPLE_TEXTS.items():
            print(f" - {dt}: {txt[:50]}...")
