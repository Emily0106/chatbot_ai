
from typing import Dict, List, Any
from app.core.taxonomy import DocType, Scope, SecurityLevel

# Legacy keys that should NOT exist
LEGACY_KEYS = {"doc_category", "commune_id"}

# Strict keys required
STRICT_KEYS = {"tenant_id", "doc_type", "scope", "security_level"}

def validate_point_payload(payload: Dict[str, Any]) -> List[str]:
    """
    Validate that Qdrant Point payload adheres to the Strict Contract.
    Returns a list of error messages (empty if valid).
    """
    errors = []
    keys = set(payload.keys())

    # 1. Check for Legacy Keys
    found_legacy = keys.intersection(LEGACY_KEYS)
    if found_legacy:
        errors.append(f"Found legacy keys: {found_legacy}")

    # 2. Check for Strict Keys
    missing = STRICT_KEYS - keys
    if missing:
        errors.append(f"Missing strict keys: {missing}")
        
    # 3. Validation Values if present
    # Tenant ID
    if "tenant_id" in payload and not isinstance(payload["tenant_id"], str):
        errors.append("tenant_id must be string")
        
    # Doc Type (must match Enum)
    if "doc_type" in payload:
        dt = payload["doc_type"]
        # Allow string match to enum value
        try:
            # Check if dt is valid enum value
            valid_types = {t.value for t in DocType}
            if dt not in valid_types:
                errors.append(f"Invalid doc_type: {dt}")
        except Exception:
            pass

    # Scope
    if "scope" in payload:
        sc_raw = str(payload["scope"])
        sc = sc_raw.strip()
        sc_norm = sc.upper()
        valid_scopes = {s.value.upper() for s in Scope}
        if sc_norm not in valid_scopes:
            errors.append(f"Invalid scope: {sc_raw}")
            
        # Scope Specific Logic
        if sc_norm == Scope.INTERNAL.value.upper():
            if "department_id" not in payload:
                errors.append("INTERNAL scope requires department_id")
            elif not payload["department_id"]:
                 errors.append("department_id is empty")

    # Security Level
    if "security_level" in payload:
        sl = payload["security_level"]
        if not isinstance(sl, int):
            errors.append(f"security_level must be int, got {type(sl)}")
        else:
            if not (1 <= sl <= 5):
                 errors.append(f"security_level out of range: {sl}")

    return errors
