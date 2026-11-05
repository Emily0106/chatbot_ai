from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny, Range
from app.core.policy.types import UserContext
from app.core.taxonomy import Scope

class PermissionError(Exception):
    """Raised when policy enforcement denies access."""
    pass

class QdrantStrictFilterBuilder:
    """
    Translates Policy Filters (dict) + User Context into a Strict Qdrant Filter.
    Fail-Closed architecture.
    """
    def _norm(self, v):
        """Normalize Enum to value if needed."""
        return v.value if hasattr(v, "value") else v

    def _norm_str(self, v) -> str:
        return str(self._norm(v) or "").strip()

    def _scope_match_condition(self, raw_scope: str) -> FieldCondition:
        """
        Scope payload casing is mixed across datasets (`PUBLIC` vs `public`).
        Build a case-tolerant filter to avoid false no_hits.
        """
        variants = []
        for candidate in (raw_scope, raw_scope.lower(), raw_scope.upper()):
            if candidate and candidate not in variants:
                variants.append(candidate)
        if len(variants) == 1:
            return FieldCondition(key="scope", match=MatchValue(value=variants[0]))
        return FieldCondition(key="scope", match=MatchAny(any=variants))

    def build(self, user_ctx: UserContext, filters: dict) -> Filter:
        must = []
        
        # 1. Tenant Isolation (Mandatory)
        if not user_ctx.tenant_id:
             raise PermissionError("Missing tenant_id in UserContext")
        must.append(FieldCondition(key="tenant_id", match=MatchValue(value=user_ctx.tenant_id)))
        
        # 2. Scope Logic
        scope_raw = filters.get("scope")
        if scope_raw:
            scope = self._norm_str(scope_raw)
            scope_upper = scope.upper()
            must.append(self._scope_match_condition(scope))
            
            # PUBLIC: Exclude PII (P1 Security)
            # Fail-Closed: Must be explicitly FALSE. Missing/Null = Deny.
            if scope_upper == Scope.PUBLIC.value:
                must.append(FieldCondition(key="contains_pii", match=MatchValue(value=False)))
                must_not = [] 
            else:
                must_not = []
            
            # INTERNAL Enforcement
            if scope_upper == Scope.INTERNAL.value: # Enum value check
                if not user_ctx.department_id:
                    raise PermissionError("INTERNAL scope requires department_id in UserContext")
                # Strict: Must match department
                must.append(FieldCondition(key="department_id", match=MatchValue(value=user_ctx.department_id)))
            
            # RESTRICTED Enforcement
            if scope_upper == Scope.RESTRICTED.value:
                # Clearance check
                clearance = getattr(user_ctx, "security_level", 0) # Default 0 (Public)
                if not isinstance(clearance, int):
                     clearance = 0
                     
                MIN_RESTRICTED_LEVEL = 3
                if clearance < MIN_RESTRICTED_LEVEL:
                    raise PermissionError(f"Access Denied: RESTRICTED requires clearance >= {MIN_RESTRICTED_LEVEL}")
                
                # Filter: 3 <= security_level <= clearance
                must.append(FieldCondition(
                    key="security_level", 
                    range=Range(gte=MIN_RESTRICTED_LEVEL, lte=clearance)
                ))

        # 3. Doc Type
        # Support both singular 'doc_type' and plural 'doc_types' (PolicyManager/Schemas vary)
        dt_raw = filters.get("doc_type") or filters.get("doc_types")
        if dt_raw:
             if isinstance(dt_raw, list):
                 dt_list = [self._norm(x) for x in dt_raw]
                 must.append(FieldCondition(key="doc_type", match=MatchAny(any=dt_list)))
             else:
                 dt = self._norm(dt_raw)
                 must.append(FieldCondition(key="doc_type", match=MatchValue(value=dt)))

        # 4. Geo Code (If present in filters, must verify context)
        # Assuming PolicyManager adds 'geo_code' to filters if Geo Isolation is active
        if "geo_code" in filters:
            if not user_ctx.geo_code:
                 raise PermissionError("Geo Scope requires geo_code in UserContext")
            must.append(FieldCondition(key="geo_code", match=MatchValue(value=user_ctx.geo_code)))

        # Build final filter
        # must_not is only defined if scope==PUBLIC above, otherwise default empty
        if 'must_not' not in locals():
            must_not = []
        return Filter(must=must, must_not=must_not)
