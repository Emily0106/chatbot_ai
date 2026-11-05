from app.core.taxonomy import DocType, Scope, SecurityLevel, IngestionError

def test_doctype_values():
    """Ensure DocType values match contract strings."""
    assert DocType.MEETING_TRANSCRIPT.value == "meeting_transcript"
    assert DocType.LAW.value == "law"
    assert DocType.OTHER.value == "other"

def test_scope_values():
    """Ensure Scope values match contract."""
    assert Scope.PUBLIC.value == "public"
    assert Scope.INTERNAL.value == "internal"
    assert Scope.RESTRICTED.value == "restricted"

def test_security_level_order():
    """Ensure SecurityLevel is ordered logically."""
    assert SecurityLevel.LEVEL_1_PUBLIC < SecurityLevel.LEVEL_5_TOP_SECRET
    assert SecurityLevel.LEVEL_3_CONFIDENTIAL == 3

def test_error_codes():
    """Ensure Error Codes are defined."""
    assert IngestionError.ERR_MISSING_TENANT_CONTEXT.value == "ERR_MISSING_TENANT_CONTEXT"
