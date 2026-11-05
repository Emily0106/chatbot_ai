from __future__ import annotations
from typing import List, Dict, Any, Optional
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

# Wrapper for Tavily Search (via HTTPX)
# https://tavily.com/

async def web_search(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """
    Perform web search using Tavily API.
    Returns list of dicts: {"title": str, "url": str, "snippet": str}
    """
    api_key = settings.TAVILY_API_KEY
    if not api_key:
        logger.warning("TAVILY_API_KEY is not set. Returning empty results.")
        return []

    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic", # or "advanced"
        "include_answer": False,
        "include_images": False,
        "include_raw_content": False,
        "max_results": num_results,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # Format results
            results = []
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", "") # Tavily returns 'content'
                })
            return results

    except Exception as e:
        logger.error(f"Tavily Search Error: {e}")
        return []

async def external_api_call(method: str, url: str, **kwargs):
    """
    Stub for external API call tool.
    Raises RuntimeError to ensure proper mocking in Tier-0 tests.
    """
    raise RuntimeError("external_api_call is not configured; mock this in Tier-0 tests")
