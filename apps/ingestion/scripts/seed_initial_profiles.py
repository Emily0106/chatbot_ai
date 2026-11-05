import sys
import os
import asyncio
from uuid import uuid5, NAMESPACE_DNS

# Ensure pythonpath includes src
sys.path.append(os.path.join(os.getcwd(), 'apps', 'ingestion', 'src'))

from app.workers.bootstrap import get_pg_repo
from app.core.canonical_models import IngestionProfile, IngestionProfileConfig
from app.core.taxonomy import Scope, DocType

# Deterministic UUID generation based on profile ID string
def gen_uuid(name: str):
    return uuid5(NAMESPACE_DNS, f"govai.profile.{name}")

PROFILES_DATA = [
    {
        "id": "profile_law_public",
        "name": "Văn bản Quy phạm pháp luật (Công khai)",
        "description": "Dành cho văn bản luật, nghị định công khai trên cổng TTĐT.",
        "config": {
            "scope": Scope.PUBLIC,
            "security_level": 1,
            "doc_type": "law",
            "auto_approve": True, # requires_approval=False
            "doc_category_override": "legal",
        }
    },
    {
        "id": "profile_procedure_public",
        "name": "Thủ tục Hành chính",
        "description": "Hướng dẫn thủ tục công dân.",
        "config": {
            "scope": Scope.PUBLIC,
            "security_level": 1,
            "doc_type": "procedure",
            "auto_approve": True,
            "doc_category_override": "procedure",
        }
    },
    {
        "id": "profile_meeting_internal",
        "name": "Biên bản Cuộc họp (Nội bộ)",
        "description": "Biên bản họp nội bộ, cần kiểm duyệt.",
        "config": {
            "scope": Scope.INTERNAL,
            "security_level": 2,
            "doc_type": "meeting_transcript",
            "auto_approve": False, # requires_approval=True
            "doc_category_override": "report", # Best match
        }
    },
    {
        "id": "profile_plan_internal",
        "name": "Kế hoạch/Lịch công tác",
        "description": "Lịch công tác tuần/tháng nội bộ.",
        "config": {
            "scope": Scope.INTERNAL,
            "security_level": 2,
            "doc_type": "plan",
            "auto_approve": True,
            "doc_category_override": "schedule",
        }
    },
    {
        "id": "profile_restricted_l3",
        "name": "Hồ sơ Mật (Cấp 3 - Restricted)",
        "description": "Tài liệu bảo mật cao, cần kiểm duyệt nghiêm ngặt.",
        "config": {
            "scope": Scope.RESTRICTED,
            "security_level": 3,
            "doc_type": "other",
            "auto_approve": False,
            "doc_category_override": "mixed", # Fallback
        }
    }
]

def seed_profiles():
    print("Initialize PostgresRepo...")
    pg = get_pg_repo()
    
    tenant_id = "default" # Use 'default' as global tenant for seeding or 'global' if supported
    # In cockpit schema, tenant_id is Text. We'll use 'default' for now as per `auth_context`.
    
    print(f"Seeding {len(PROFILES_DATA)} profiles for tenant '{tenant_id}'...")
    
    count = 0
    with pg._conn() as conn:
        with conn.cursor() as cur:
            for p in PROFILES_DATA:
                profile_id = gen_uuid(p["id"])
                print(f"  - Upserting: {p['id']} ({profile_id}) -> {p['name']}")
                
                # We reuse PostgresRepo.create_profile logic but do Upsert (ON CONFLICT)
                # create_profile currently does INSERT only and raises error on conflict.
                # We will perform RAW execute here for Upsert capability to be idempotent.
                
                config = IngestionProfileConfig(**p["config"])
                import json
                config_json = config.model_dump_json()
                
                sql = """
                INSERT INTO ingestion_profiles (
                    profile_id, tenant_id, name, description, config, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, now()
                )
                ON CONFLICT (tenant_id, name) 
                DO UPDATE SET
                    description = EXCLUDED.description,
                    config = EXCLUDED.config,
                    updated_at = now();
                """
                
                cur.execute(sql, (
                    str(profile_id),
                    tenant_id,
                    p["name"],
                    p["description"],
                    config_json
                ))
                count += 1
        conn.commit()
    
    print(f"✅ Success: {count} Profiles Created/Updated.")

if __name__ == "__main__":
    seed_profiles()
