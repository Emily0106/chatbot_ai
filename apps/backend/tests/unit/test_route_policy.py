from app.core.route_policy import decide_route_mode


def test_smalltalk_routes_to_llm_only():
    d = decide_route_mode(query="xin chào", agent_id="legal", security_level=1)
    assert d.mode == "llm_only"
    assert d.reason == "smalltalk"
    assert d.is_smalltalk is True
    assert d.is_evidence_required is False


def test_meta_chat_routes_to_llm_only():
    d = decide_route_mode(query="bạn là agent gì", agent_id="legal", security_level=1)
    assert d.mode == "llm_only"
    assert d.reason == "agent_intro"
    assert d.is_agent_intro is True
    assert d.is_evidence_required is False


def test_evidence_query_stays_rag():
    d = decide_route_mode(query="Điều 5 quy định gì?", agent_id="legal", security_level=1)
    assert d.mode == "rag_lexical"
    assert d.reason == "literal_or_evidence_hint"
    assert d.prefer_lexical is True
    assert d.is_evidence_required is True
    assert d.is_general_explain is False


def test_latest_legal_query_is_evidence_required():
    d = decide_route_mode(
        query="cung cấp thông tin về luật sở hữu trí tuệ mới nhất",
        agent_id="legal",
        security_level=1,
    )
    assert d.mode == "rag_lexical"
    assert d.is_evidence_required is True
    assert d.is_general_explain is False


def test_aggregate_query_marks_sql_candidate():
    d = decide_route_mode(query="bao nhiêu văn bản hiện hành", agent_id="legal", security_level=1)
    assert d.mode == "sql_candidate"
    assert d.sql_candidate is True


def test_high_security_defaults_to_rag_vector():
    d = decide_route_mode(query="hướng dẫn quy trình tuyển dụng công chức", agent_id="legal", security_level=3)
    assert d.mode == "rag_vector"
    assert d.reason == "security_level_high"
    assert d.is_how_to is True


def test_how_to_routes_to_llm_only_without_evidence_strictness():
    d = decide_route_mode(
        query="Hướng dẫn tôi cách ingest tài liệu vào hệ thống",
        agent_id="legal",
        security_level=1,
    )
    assert d.mode == "llm_only"
    assert d.reason == "how_to"
    assert d.is_how_to is True
    assert d.is_evidence_required is False


def test_general_explain_detected_without_evidence_keywords():
    d = decide_route_mode(query="giải thích khái niệm quyền tác giả", agent_id="legal", security_level=1)
    assert d.mode == "rag_vector"
    assert d.reason == "general_explain"
    assert d.is_general_explain is True
    assert d.is_evidence_required is False
