# Wrapper for Tavily/Google Search
import os
import logging
import asyncio
from typing import List, Optional
from app.config import settings

logger = logging.getLogger(__name__)


class SearchResult:
    """Class kết quả tìm kiếm chuẩn"""
    def __init__(self, title: str, link: str, snippet: str):
        self.title = title
        self.link = link
        self.snippet = snippet


class WebSearchService:
    def __init__(self):
        # Lấy key thông qua pydantic-settings
        self.tavily_key = settings.TAVILY_API_KEY
        self.google_key = getattr(settings, "GOOGLE_API_KEY", None)

    async def search(self, query: str, num_results: int = 3) -> List[SearchResult]:
        """
        Hàm search theo thứ tự ưu tiên:
          1. Tavily (nếu có TAVILY_API_KEY)
          2. DuckDuckGo (miễn phí, không cần key — dùng cho test)
          3. Mock offline (fallback cuối cùng)
        """
        # --- TIER 1: Tavily (chất lượng cao, có key mới chạy) ---
        if self.tavily_key:
            try:
                return await self._tavily_search(query, num_results)
            except Exception as e:
                logger.warning(f"[WebSearch] Tavily failed, fallback to DDG: {e}")

        # --- TIER 2: DuckDuckGo (FREE, không cần key, dùng để test) ---
        try:
            return await self._ddg_search(query, num_results)
        except Exception as e:
            logger.warning(f"[WebSearch] DuckDuckGo failed, fallback to mock: {e}")

        # --- TIER 3: Mock offline (dev/debug không có internet) ---
        logger.info(f"[WebSearch][MOCK] Returning mock results for: {query}")
        return self._mock_search(query, num_results)

    # ----------------------------------------------------------------
    # TIER 2: DuckDuckGo (Free, No Key Required)
    # ----------------------------------------------------------------
    async def _ddg_search(self, query: str, num_results: int) -> List[SearchResult]:
        """Dùng thư viện duckduckgo-search (pip install duckduckgo-search>=6.0.0)"""

        def _sync_search():
            results = []
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                from duckduckgo_search import DDGS
                with DDGS() as ddgs:
                    for r in ddgs.text(
                        query,
                        region="vn-vi",        # Ưu tiên kết quả tiếng Việt
                        safesearch="moderate",
                        max_results=num_results
                    ):
                        results.append(SearchResult(
                            title=r.get("title", ""),
                            link=r.get("href", "#"),
                            snippet=r.get("body", "")
                        ))
            return results

        # Chạy sync trong thread để không block event loop
        return await asyncio.to_thread(_sync_search)

    # ----------------------------------------------------------------
    # TIER 1: Tavily (Paid, High Quality)
    # ----------------------------------------------------------------
    async def _tavily_search(self, query: str, num_results: int) -> List[SearchResult]:
        """TODO: Lắp Tavily API khi có key."""
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_key,
                    "query": query,
                    "num_results": num_results,
                    "search_depth": "basic",
                },
                timeout=10.0
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                SearchResult(
                    title=r.get("title", ""),
                    link=r.get("url", "#"),
                    snippet=r.get("content", "")
                )
                for r in data.get("results", [])[:num_results]
            ]

    # ----------------------------------------------------------------
    # TIER 3: Mock Offline (Fallback)
    # ----------------------------------------------------------------
    def _mock_search(self, query: str, num_results: int) -> List[SearchResult]:
        """Kết quả giả lập khi không có internet. Chỉ để dev/debug."""
        if any(kw in query.lower() for kw in ["mẫu", "đơn", "tờ khai"]):
            mock = [
                SearchResult(
                    title="Tải mẫu đơn đề nghị cấp đổi CCCD (Mẫu CC01)",
                    link="https://bocongan.gov.vn/bieu-mau/cc01.doc",
                    snippet="Mẫu CC01 dùng cho công dân kê khai khi làm thẻ Căn cước công dân gắn chip..."
                ),
                SearchResult(
                    title="Hướng dẫn điền tờ khai Căn cước công dân",
                    link="https://luatvietnam.vn/hanh-chinh/to-khai-cccd.html",
                    snippet="Chi tiết cách ghi các mục trong tờ khai. Mục 1 ghi họ tên in hoa..."
                )
            ]
        else:
            mock = [
                SearchResult(
                    title=f"Thông tin mới nhất về {query}",
                    link="https://baochinhphu.vn/tin-tuc",
                    snippet=f"Tổng hợp văn bản chỉ đạo mới nhất liên quan đến {query}..."
                ),
                SearchResult(
                    title=f"Hướng dẫn thủ tục {query} năm 2026",
                    link="https://dichvucong.gov.vn/huong-dan",
                    snippet=f"Cổng DVCQG hướng dẫn chi tiết quy trình thực hiện {query} trực tuyến..."
                )
            ]
        return mock[:num_results]


# Hàm wrapper để gọi nhanh
async def web_search(query: str, num_results: int = 3) -> List[SearchResult]:
    service = WebSearchService()
    return await service.search(query, num_results)
