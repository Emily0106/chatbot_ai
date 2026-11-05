
# apps/backend/src/app/core/policy/manager.py
import logging
from typing import Dict, Any, Optional

from app.core.policy.config import AGENT_POLICIES, AgentPolicy
from app.core.policy.types import UserContext
from app.core.policy.errors import MissingContextError
from app.core.taxonomy import DocType, normalize_doctype, DataScope
from app.schemas.chat import RetrievalFilters

logger = logging.getLogger(__name__)

ALLOWLIST_REQUEST_FILTERS = {
    "year", "date_from", "date_to", "topic", "tags", "doc_id", 
    "domain", "status", "parent_id", "from_date", "to_date"
}

class PolicyManager:
    @staticmethod
    def get_policy(agent_id: str) -> AgentPolicy:
        if agent_id not in AGENT_POLICIES:
            raise ValueError(f"Unknown agent_id '{agent_id}'. Policy denied (Fail-Closed).")
        return AGENT_POLICIES[agent_id]

    @staticmethod
    def enforce_context(agent_id: str, user_ctx: UserContext) -> None:
        """
        Enforce required context fields defined in AgentPolicy.
        Raises MissingContextError if any required field is missing/empty in context.
        """
        policy = PolicyManager.get_policy(agent_id)
        
        # Backward compatibility for legacy policies (dict or old class)
        required = []
        if isinstance(policy, dict):
            required = policy.get("required_context_fields") or []
        else:
            required = getattr(policy, "required_context_fields", None) or []

        if not required:
            return

        missing = []
        for field in required: # Corrected from policy.required_context_fields
            val = getattr(user_ctx, field, None)
            # Check for generic "empty" values (None, "", [], {})
            if val in (None, "", [], {}):
                missing.append(field)
        
        if missing:
            logger.warning(f"Context Violation: Agent {agent_id} missing fields: {missing}")
            raise MissingContextError(field=f"required_context_fields: {missing}", agent_id=agent_id)

    @staticmethod
    def enforce_filters(
        agent_id: str, 
        user_ctx: UserContext, 
        request_filters: Optional[RetrievalFilters] = None
    ) -> Dict[str, Any]:
        """
        Master Logic: FinalFilter = AgentPolicy AND UserPermission AND RequestFilters
        """
        
        policy = PolicyManager.get_policy(agent_id)
        
        # 1. Base Constraints (Must)
        # --------------------------
        # DocTypes: Intersection of Policy & Request
        allowed_doctypes = {dt.value for dt in policy.allowed_doc_types}
        
        # Determine final doc_type constraint
        req_dtype = request_filters.doc_type if request_filters else None
        
        final_doc_type = None
        policy_conflict = False
        
        if req_dtype:
            # If request asks for specific doc type
            norm_req = normalize_doctype(req_dtype)
            if norm_req and norm_req.value in allowed_doctypes:
                final_doc_type = norm_req.value
            else:
                final_doc_type = "__DENIED_BY_POLICY__" 
                policy_conflict = True
                logger.warning(f"Policy Conflict: Agent {agent_id} req doc_type={req_dtype} not in policy.")
        else:
             pass

        # 2. Scope / Isolation Logic
        # --------------------------
        must_filters = {}
        
        # Department Isolation
        if policy.isolation_level == "department":
            if user_ctx.department_id:
                must_filters["department_id"] = user_ctx.department_id
            else:
                # Policy requires isolation but context missing -> Raise 403-able error
                logger.warning(f"Isolation Violation: Agent {agent_id} requires department_id.")
                raise MissingContextError(field="department_id", agent_id=agent_id)

        # Geo Isolation
        if policy.isolation_level == "geo":
            if user_ctx.geo_code:
                must_filters["geo_code"] = user_ctx.geo_code
            else:
                logger.warning(f"Isolation Violation: Agent {agent_id} requires geo_code.")
                raise MissingContextError(field="geo_code", agent_id=agent_id)

        # Security Level Enforce
        max_lvl = 5
        if policy.max_security_level is not None:
             max_lvl = min(max_lvl, policy.max_security_level)
        if user_ctx.security_level is not None:
             max_lvl = min(max_lvl, user_ctx.security_level)
             
        req_lvl = request_filters.security_level if request_filters else None
        if req_lvl:
            final_lvl = min(req_lvl, max_lvl)
        else:
            final_lvl = max_lvl
            
        must_filters["security_level"] = final_lvl

        # INJECT SCOPE (Trusted Source Precedence)
        # 1. User Context (Strongest, trusted via token/gateway)
        # 2. Agent Default (Fallback)
        # 3. Validation against Allowed
        
        target_scope = user_ctx.scope if user_ctx.scope else None
        if not target_scope and policy.default_scope:
             target_scope = policy.default_scope.value
             
        # Validate against allowed
        allowed_scopes_vals = {s.value for s in policy.allowed_scopes}
        
        if target_scope and target_scope in allowed_scopes_vals:
             must_filters["scope"] = target_scope
        else:
             # Logic Hole: What if target_scope is invalid or missing?
             # Fallback to default if available and allowed logic.
             if policy.default_scope and policy.default_scope.value in allowed_scopes_vals:
                 must_filters["scope"] = policy.default_scope.value
                 if target_scope:
                      logger.warning(f"Scope Mismatch (Fallback): Agent {agent_id} requested {target_scope} (invalid/not allowed). Used default: {policy.default_scope.value}")
             else:
                 # No valid scope can be determined -> Fail Closed or rely on Agent-Specific Implicit behavior?
                 # If we leave it empty, some downstream might default Public. 
                 # But we can't invent a scope.
                 if target_scope:
                      logger.warning(f"Scope Mismatch (No Fallback): Agent {agent_id} requested {target_scope} but allows {allowed_scopes_vals}")

        # 3. Merge Allowlist Request Filters
        # ----------------------------------
        if request_filters:
            req_dict = request_filters.model_dump(exclude_none=True)
            for k, v in req_dict.items():
                if k in ALLOWLIST_REQUEST_FILTERS:
                    must_filters[k] = v
                elif k == "doc_type":
                    pass # Handled above
                elif k == "security_level":
                    pass # Handled above
                # Ignore others
        
        # 4. Construct Output
        # -------------------
        # Used by CoreService to call db_vector
        result = {
            "filters": must_filters,
            "policy_meta": {
                "agent_id": agent_id,
                "conflict": policy_conflict,
                "final_doc_type_constraint": final_doc_type,
                "allowed_doc_types": list(allowed_doctypes)
            }
        }
        
        if final_doc_type == "__DENIED_BY_POLICY__":
             result["filters"]["doc_type"] = "__DENIED_BY_POLICY__"
        elif final_doc_type:
             result["filters"]["doc_type"] = final_doc_type
        elif allowed_doctypes:
             # Multiple types allowed AND no specific user conflict
             # If user_request was None, we enforce ALL allowed types.
             # e.g. meeting + schedule
             # Check if we have multiple
             if len(allowed_doctypes) == 1:
                  result["filters"]["doc_type"] = list(allowed_doctypes)[0]
             else:
                  # Multiple allowed -> Pass list
                  result["filters"]["doc_types"] = list(allowed_doctypes)

        
        return result
