import pytest

pytestmark = pytest.mark.integration

from app.core.rag.temp_evidence import evaluate_temp_chunks


def test_evaluate_gate_logic():
    chunks = [{"text": "Biên bản cuộc họp về dự án AI", "chunk_id": "c1"}]
    res = evaluate_temp_chunks(chunks, "Họp dự án AI", base_score=0.5)
    assert len(res) == 1
    assert res[0]["score"] > 0.5
    assert "overlap=" in res[0]["gate_reason"]

    chunks = [{"text": "Báo cáo tài chính năm 2023", "chunk_id": "c2"}]
    assert evaluate_temp_chunks(chunks, "Kế hoạch marketing", base_score=0.5) == []


def test_temp_gate_rejects_stopword_only_query():
    chunks = [{"text": "Đây là của tôi", "chunk_id": "c3"}]
    assert evaluate_temp_chunks(chunks, "là của") == []
