from enum import Enum
from typing import NewType

# ==========================================
# 1. Identity Types (Strict Typing)
# ==========================================
TenantId = NewType("TenantId", str)
DepartmentId = NewType("DepartmentId", str)
GeoCode = NewType("GeoCode", str)

# ==========================================
# 2. Enums (Matches Backend Policy)
# ==========================================

class DocType(str, Enum):
    """
    Strict Document Types mapping to Backend Policy.
    Replaces legacy 'DocCategory'.
    """
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

    # Fallback
    OTHER = "other"


class Scope(str, Enum):
    """
    Data Visibility Scope.
    """
    PUBLIC = "public"       # Visible to citizens
    INTERNAL = "internal"   # Visible to staff only (requires department_id)
    RESTRICTED = "restricted" # Sensitive (requires security_level check)


# ==========================================
# 3. Security Constants
# ==========================================

class SecurityLevel(int, Enum):
    """
    Access Control Levels (1-5).
    """
    LEVEL_1_PUBLIC = 1
    LEVEL_2_INTERNAL = 2
    LEVEL_3_CONFIDENTIAL = 3
    LEVEL_4_SECRET = 4
    LEVEL_5_TOP_SECRET = 5


# ==========================================
# 4. Error Codes (Fail-Closed)
# ==========================================

class IngestionError(str, Enum):
    ERR_UNAUTHORIZED_CALLER = "ERR_UNAUTHORIZED_CALLER"
    ERR_MISSING_TENANT_CONTEXT = "ERR_MISSING_TENANT_CONTEXT"
    ERR_MISSING_DEPARTMENT_CONTEXT = "ERR_MISSING_DEPARTMENT_CONTEXT"
    ERR_SCOPE_SECURITY_VIOLATION = "ERR_SCOPE_SECURITY_VIOLATION"
    ERR_INVALID_DOC_TYPE = "ERR_INVALID_DOC_TYPE"
    ERR_INVALID_SCOPE = "ERR_INVALID_SCOPE"
    ERR_FILE_TOO_LARGE = "ERR_FILE_TOO_LARGE"
    ERR_UNSUPPORTED_FILE_TYPE = "ERR_UNSUPPORTED_FILE_TYPE"
    ERR_ENQUEUE_FAILED = "ERR_ENQUEUE_FAILED"
    ERR_INVALID_SECURITY_LEVEL = "ERR_INVALID_SECURITY_LEVEL"
