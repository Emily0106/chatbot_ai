import os
# Force CI_MODE = True to bypass Settings validation (offline mode)
os.environ["CI_MODE"] = "true"

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agents.contract import TrustedContext, RefusalCode
from app.agents.registry import registry
from app.agents.agri_agent import AgriAgent

# Helper for async generator (mocking get_async_db)
class _DummyAsyncGen:
    def __init__(self, value):
        self.value = value
        self._done = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._done:
            raise StopAsyncIteration
        self._done = True
        return self.value

@pytest.fixture
def agent():
    return AgriAgent()

@pytest.mark.asyncio
async def test_agri_agent_refuse_when_no_evidence(agent):
    ctx = TrustedContext(tenant_id="t1", user_id="dev", security_level=1)

    mock_rag = AsyncMock()
    mock_rag.context = ""
    mock_rag.citations = []
    mock_rag.meta = {}

    with patch("app.core.db_sql.get_async_db", return_value=_DummyAsyncGen(object())), \
         patch("app.core.rag.pipeline.rag_retrieve", return_value=mock_rag), \
         patch("app.core.llm_client.achat", return_value="SHOULD_NOT_BE_CALLED"):
        
        # Calling process
        resp = await agent.process(ctx, "Hướng dẫn trồng lúa vụ đông xuân?")
        
        # Expect Refusal
        # ChatMeta is Pydantic model, use getattr or convert to dict
        meta_dict = resp.meta.model_dump() if hasattr(resp.meta, "model_dump") else resp.meta.__dict__
        assert meta_dict.get("refusal", {}).get("code") == RefusalCode.NO_EVIDENCE


@pytest.mark.asyncio
async def test_agri_agent_rag_happy_path_and_sanitizes_doc_types(agent):
    ctx = TrustedContext(
        tenant_id="t1",
        user_id="dev",
        security_level=1,
    )
    # giả lập request_payload có doc_types “lạ” -> agent phải lọc về allowlist
    ctx.request_payload = {"filters": {"doc_types": ["agri_tech", "SECRET_DOC"]}}  

    mock_rag = AsyncMock()
    mock_rag.context = "Kỹ thuật canh tác: ... (trang 2)"
    mock_rag.citations = [{"chunk_id": "1", "title": "Tài liệu A", "page_number": 2, "snippet": "Kỹ thuật..."}]
    mock_rag.meta = {}

    with patch("app.core.db_sql.get_async_db", return_value=_DummyAsyncGen(object())), \
         patch("app.core.rag.pipeline.rag_retrieve", return_value=mock_rag) as mock_retrieve, \
         patch("app.core.llm_client.achat", return_value="Trả lời dựa trên tài liệu A."):
        
        resp = await agent.process(ctx, "Kỹ thuật bón phân cho lúa?")
        
        assert resp.answer == "Trả lời dựa trên tài liệu A."
        assert len(resp.citations) == 1

        # verify filters đã bị sanitize (SECRET_DOC bị loại)
        call_kwargs = mock_retrieve.call_args.kwargs
        used_filters = call_kwargs["filters"]
        
        # RetrievalFilters object or dict depending on implementation
        # The agent code does: filters=RetrievalFilters(**safe_filters_dict)
        # So it passes an OBJECT.
        doc_types = getattr(used_filters, "doc_types", [])
        
        assert "agri_tech" in doc_types
        assert "SECRET_DOC" not in doc_types


@pytest.mark.asyncio
async def test_agri_agent_weather_tool_can_provide_evidence_without_rag(agent):
    ctx = TrustedContext(tenant_id="t1", user_id="dev", security_level=1)
    ctx.geo_code = "VN-HN"  

    mock_rag = AsyncMock()
    mock_rag.context = ""
    mock_rag.citations = []
    mock_rag.meta = {}

    mock_weather = AsyncMock(return_value={
        "location": "Hà Nội",
        "updated_at": "Just now",
        "summary": "Dự báo 24h tới: Rain, 25°C",
        "source_url": "https://openweathermap.org/city/123"
    })

    # IMPORTANT: We verify that the AGENT logic handles the tool result correctly.
    # We DO NOT test the actual weather_api implementation here (it's integration test).
    
    with patch("app.core.db_sql.get_async_db", return_value=_DummyAsyncGen(object())), \
         patch("app.core.rag.pipeline.rag_retrieve", return_value=mock_rag), \
         patch("app.core.tools.weather.weather_api", mock_weather), \
         patch("app.core.llm_client.achat", return_value="Khuyến cáo: Mưa nhiều..."):
        
        resp = await agent.process(ctx, "Thời tiết Hà Nội hôm nay?")
        
        assert resp.answer
        # phải có citation từ weather tool
        assert any(getattr(c, "file_url", "").startswith("https://openweathermap.org") for c in resp.citations)


@pytest.mark.asyncio
async def test_agri_agent_market_web_search_adds_citations(agent):
    ctx = TrustedContext(tenant_id="t1", user_id="dev", security_level=1)
    ctx.geo_code = "VN-SG"  

    mock_rag = AsyncMock()
    mock_rag.context = "Nguyên tắc thị trường: ... (doc nội bộ)"
    mock_rag.citations = [{"chunk_id": "2", "title": "Doc market", "page_number": 1, "snippet": "Nguyên tắc..."}]
    mock_rag.meta = {}

    mock_web_search = AsyncMock(return_value=[
        {"title": "Giá lúa hôm nay", "url": "https://news.com/rice", "snippet": "Lúa tăng 500đ..."},
        {"title": "Thị trường xuất khẩu", "url": "https://market.com/export", "snippet": "Nhu cầu cao..."},
    ])

    with patch("app.core.db_sql.get_async_db", return_value=_DummyAsyncGen(object())), \
         patch("app.core.rag.pipeline.rag_retrieve", return_value=mock_rag), \
         patch("app.core.tools.web.web_search", mock_web_search), \
         patch("app.core.llm_client.achat", return_value="Tóm tắt xu hướng giá..."):
        
        resp = await agent.process(ctx, "Giá lúa tại TP.HCM?")
        
        assert resp.answer
        assert len(resp.citations) >= 2
        # Verify citation sources
        sources = [getattr(c, "file_url", "") for c in resp.citations]
        assert "https://news.com/rice" in sources
