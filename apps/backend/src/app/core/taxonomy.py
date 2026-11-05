
# apps/backend/src/app/core/taxonomy.py
from enum import Enum
from typing import Optional

class DocType(str, Enum):
    # Meeting Domain
    MEETING_TRANSCRIPT = "meeting_transcript"
    MEETING_SCHEDULE = "meeting_schedule"
    
    # Legal Domain
    LAW = "law"                    # Luật
    DECREE = "decree"              # Nghị định
    CIRCULAR = "circular"          # Thông tư
    DECISION = "decision"          # Quyết định
    
    # Procedures & Services
    ADMIN_PROCEDURE = "admin_procedure" # Thủ tục hành chính
    
    # Specialized
    LAND_PLAN = "land_plan"
    WELFARE_POLICY = "welfare_policy"
    PUBLIC_NEWS = "public_news"
    PLAN = "plan"
    
    # Wave 2 Additions
    CITIZEN_GUIDE = "citizen_guide"
    INTERNAL_REPORT = "internal_report"
    STATS = "stats"
    HEALTH_GUIDELINES = "health_guidelines"
    DISEASE_INFO = "disease_info"
    CULTURE_GUIDE = "culture_guide"
    TOURISM_SPOTS = "tourism_spots"
    AGRI_TECH = "agri_tech"
    MEETING_MINUTES = "meeting_minutes"
    OFFICIAL_DOCUMENT = "official_document"
    LAND_PLANNING = "land_planning" # Alias or specific
    CONSTRUCTION_PERMIT = "construction_permit"
    SOCIAL_POLICY = "social_policy"

    # Fallback
    OTHER = "other"

class Scope(str, Enum):
    """
    Data Visibility Scope.
    Aligned with Ingestion Service.
    """
    PUBLIC = "PUBLIC"       
    INTERNAL = "INTERNAL"   
    RESTRICTED = "RESTRICTED" 

# Alias for backward compatibility if backend legacy code uses DataScope
DataScope = Scope

class SecurityLevel(int, Enum):
    """
    Access Control Levels (1-5).
    """
    LEVEL_1_PUBLIC = 1
    LEVEL_2_INTERNAL = 2
    LEVEL_3_CONFIDENTIAL = 3
    LEVEL_4_SECRET = 4
    LEVEL_5_TOP_SECRET = 5

class GeoLevel(str, Enum):
    XA = "xa"
    HUYEN = "huyen"
    TINH = "tinh"
    CENTRAL = "central"

def normalize_doctype(value: Optional[str]) -> Optional[DocType]:
    """
    Helper to safely parse string to DocType. 
    Returns None if invalid or None.
    """
    if not value:
        return None
    try:
        return DocType(value.lower().strip())
    except ValueError:
        return None
