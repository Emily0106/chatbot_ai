from app.core.router import decide_lane, LaneDecision

def test_decide_lane_strict_conditions():
    # 1. Legal terms
    res = decide_lane(query="quy định về thuế", agent_id="qa", security_level=1)
    assert res.lane == "strict"
    assert res.reason == "legal_hint"

    # 2. PII terms
    res = decide_lane(query="số cmnd của tôi", agent_id="qa", security_level=1)
    assert res.lane == "strict"
    assert res.reason == "pii_hint"

    # 3. Security Level
    res = decide_lane(query="hi", agent_id="qa", security_level=2)
    assert res.lane == "strict"
    assert res.reason == "security_level_high"

    # 4. Sensitive Agent
    res = decide_lane(query="hi", agent_id="legal", security_level=1)
    assert res.lane == "strict"
    assert res.reason == "sensitive_agent"

def test_decide_lane_fast_conditions():
    # Simple query
    res = decide_lane(query="xin chào", agent_id="qa", security_level=1)
    assert res.lane == "fast"
    assert res.reason == "short_simple_query"

    # Too long -> strict
    long_q = "a" * 81
    res = decide_lane(query=long_q, agent_id="qa", security_level=1)
    assert res.lane == "strict"
    assert res.reason == "default_conservative"
