
import pytest

pytestmark = pytest.mark.integration
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from app.core.policy.types import UserContext
from app.core.rag.qdrant_filter_builder import QdrantStrictFilterBuilder, PermissionError
from app.core.policy.contract_validator import validate_point_payload

@pytest.fixture
def qdrant_client():
    client = QdrantClient(":memory:")
    client.recreate_collection(
        collection_name="test_collection",
        vectors_config={"dense": VectorParams(size=768, distance=Distance.COSINE)}
    )
    return client

@pytest.fixture
def builder():
    return QdrantStrictFilterBuilder()

@pytest.fixture
def seeded_qdrant(qdrant_client):
    points = [
        # T1 Public
        PointStruct(id=1, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "law", "scope": "public", "security_level": 1}),
        # T1 Internal HR
        PointStruct(id=2, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "meeting_transcript", "scope": "internal", "department_id": "HR", "security_level": 2}),
        # T1 Restricted Level 3
        PointStruct(id=3, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "land_plan", "scope": "restricted", "security_level": 3}),
        # T1 Restricted Level 4
        PointStruct(id=4, vector={"dense": [0.1]*768}, payload={"tenant_id": "T1", "doc_type": "land_plan", "scope": "restricted", "security_level": 4}),
        # T2 Public
        PointStruct(id=5, vector={"dense": [0.1]*768}, payload={"tenant_id": "T2", "doc_type": "law", "scope": "public", "security_level": 1}),
    ]
    # Validate
    for p in points:
        errors = validate_point_payload(p.payload)
        assert not errors, f"Seed error {p.id}: {errors}"
        
    qdrant_client.upsert("test_collection", points)
    return qdrant_client

def run_query(client, builder, user_ctx, filters):
    """Helper to run build -> query"""
    q_filter = builder.build(user_ctx=user_ctx, filters=filters)
    # Using count for simplicity
    return client.count("test_collection", count_filter=q_filter).count

def test_builder_tenant_isolation(seeded_qdrant, builder):
    ctx_t1 = UserContext(tenant_id="T1")
    ctx_t2 = UserContext(tenant_id="T2")
    
    # T1 Query
    count_t1 = run_query(seeded_qdrant, builder, ctx_t1, filters={}) 
    # Logic: If filters={} -> Scope filter is NOT applied, but tenant IS.
    # Qdrant should see T1 points.
    # Wait, my Builder logic: "If scope in filters: add condition".
    # If NO scope in filters, does it Default allow?
    # Usually PolicyManager ensures scope is present (public or internal).
    # But if filters is empty map?
    # The Builder only adds strict Tenant ID.
    # So it returns ALL T1 docs (Public + Internal + Restricted if not scoped).
    # This assumes backend Policy Manager forces keys. 
    # Strict Builder respects INPUT dictionary.
    
    # Should find T1 docs (id=1,2,3,4) = 4
    assert count_t1 == 4 
    
    # T2 Query
    count_t2 = run_query(seeded_qdrant, builder, ctx_t2, filters={})
    assert count_t2 == 1 # Only id=5

def test_builder_internal_enforcement(seeded_qdrant, builder):
    # Case 1: Internal Allowed (Dept Match)
    ctx = UserContext(tenant_id="T1", department_id="HR")
    filters = {"scope": "internal", "department_id": "HR"} # Policy would inject this
    
    count = run_query(seeded_qdrant, builder, ctx, filters)
    assert count == 1 # Matches id=2
    
    # Case 2: Internal Blocked (Wrong Dept in Filter vs Context?)
    # Usually Context overrides. But Builder verifies Context matches Filter if Filter requests Internal.
    # If Context has Dept=FIN, but Filter asks Dept=HR?
    # Builder Code: "must.append(department_id=user_ctx.department_id)"
    # It IGNORES 'department_id' in input filters? No.
    # Code: "INTERNAL scope requires department_id in UserContext" -> "must.append(department_id, match=ctx.dept)"
    # So it enforces Context Dept.
    
    # Test: User FIN, Filter Internal (implicitly Dept=FIN).
    ctx_fin = UserContext(tenant_id="T1", department_id="FIN")
    filters = {"scope": "internal"}
    count_fin = run_query(seeded_qdrant, builder, ctx_fin, filters)
    assert count_fin == 0 # No FIN docs
    
    # Case 3: Missing Dept in Context -> Exception
    ctx_nodes = UserContext(tenant_id="T1", department_id=None)
    with pytest.raises(PermissionError, match="department_id"):
        builder.build(ctx_nodes, {"scope": "internal"})

def test_builder_restricted_enforcement(seeded_qdrant, builder):
    # Case 1: Clearance 3 -> matches Level 3 (id=3) but NOT Level 4 (id=4). Matches Level < 3? No, min is 3. 
    # Restricted logic: range [3, clearance].
    
    ctx = UserContext(tenant_id="T1", security_level=3)
        
    filters = {"scope": "restricted"}
    count = run_query(seeded_qdrant, builder, ctx, filters)
    assert count == 1 # Only id=3
    
    # Case 2: Clearance 5 -> matches Level 3 and 4
    ctx_high = UserContext(tenant_id="T1", security_level=5)
    count_high = run_query(seeded_qdrant, builder, ctx_high, filters)
    assert count_high == 2 # id=3 and 4
    
    # Case 3: Clearance 2 -> Exception (Denied)
    ctx_low = UserContext(tenant_id="T1", security_level=2)
    with pytest.raises(PermissionError, match="Access Denied"):
        builder.build(ctx_low, filters)
