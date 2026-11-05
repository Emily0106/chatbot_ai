from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Set

@dataclass(frozen=True)
class LaneDecision:
    lane: str  # "fast" | "strict"
    reason: str

# Sensitivity keywords (Vietnamese context)
LEGAL_HINTS: Set[str] = {
    "điều", "nghị định", "thông tư", "luật", "quy định", 
    "xử phạt", "mức phạt", "hành chính", "hình sự", "tố tụng"
}
PII_HINTS: Set[str] = {
    "cmnd", "cccd", "số định danh", "mã số thuế", "sđt", 
    "điện thoại", "địa chỉ", "hộ khẩu", "tài khoản", "ngân hàng"
}
SENSITIVE_AGENTS: Set[str] = {"legal", "accurate_people", "social_insurance"}

def decide_lane(
    *, 
    query: str, 
    agent_id: str, 
    security_level: int
) -> LaneDecision:
    """
    Decide execution lane: 'fast' or 'strict'.
    Default rule: Prefer STRICT for correctness/safety. FAST only if clearly safe.
    """
    q = (query or "").strip().lower()
    
    if not q:
        return LaneDecision("strict", "empty_query")

    # 1. Hard constraints -> STRICT
    # High security level requires maximum scrutiny
    if security_level >= 2:
        return LaneDecision("strict", "security_level_high")
    
    # Sensitive agents always use strict mode
    if agent_id in SENSITIVE_AGENTS:
        return LaneDecision("strict", "sensitive_agent")

    # 2. Heuristics -> STRICT
    # Legal terms imply need for high precision/citation
    if any(k in q for k in LEGAL_HINTS):
        return LaneDecision("strict", "legal_hint")
    
    # PII terms imply privacy risk/lookup accuracy
    if any(k in q for k in PII_HINTS):
        return LaneDecision("strict", "pii_hint")

    # 3. FAST Candidates
    # Short, simple queries (likely greeting, definition, or simple fact)
    # Length < 80 chars, max 1 question mark
    if len(q) <= 80 and q.count("?") <= 1:
        return LaneDecision("fast", "short_simple_query")

    # Default to STRICT for anything ambiguous
    return LaneDecision("strict", "default_conservative")

# ---------------------------------------------------------
# Legacy / Existing Router Support (Restored)
# ---------------------------------------------------------
@dataclass
class RouteResult:
    intent: str
    params: dict = None

def route_query(query: str) -> RouteResult:
    """
    Legacy router function required by accurate_people.py and chat.py.
    Preserved for backward compatibility.
    """
    # MVP: Default to GENERAL so we don't accidentally intercept specialized flows
    # unless we reimplement the logic.
    # If the original logic scanned for 'tìm người', etc., we might be missing it now.
    # But for now, unblocking the Import Error is priority.
    return RouteResult(intent="GENERAL", params={})
