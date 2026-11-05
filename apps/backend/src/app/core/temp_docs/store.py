# apps/backend/src/app/core/temp_docs/store.py
from __future__ import annotations

import json
import logging
import uuid
import time
from typing import List, Dict, Any, Optional

from app.config import settings
from app.core.cache import _get_client
from app.core.temp_docs.search import lexical_rank

logger = logging.getLogger(__name__)

class TempDocStore:
    """
    Redis-backed store for temporary documents.
    Enforces Tenant Isolation via key prefix.
    """
    
    @staticmethod
    def _key(tenant_id: str, temp_doc_id: str) -> str:
        return f"tempdoc:{tenant_id}:{temp_doc_id}"

    @classmethod
    async def save(
        cls, 
        tenant_id: str, 
        text: str, 
        chunks: List[Dict[str, Any]], 
        meta: Dict[str, Any],
        content_hash: Optional[str] = None
    ) -> str:
        """
        Save temp doc to Redis with TTL.
        Returns temp_doc_id.
        """
        temp_doc_id = f"tmp_{uuid.uuid4().hex}"
        key = cls._key(tenant_id, temp_doc_id)
        
        ttl = getattr(settings, "TEMP_DOC_TTL", 3600)
        
        data = {
            "temp_doc_id": temp_doc_id,
            "tenant_id": tenant_id,
            "created_at": time.time(),
            "expires_in": ttl,
            "meta": meta,
            "text": text, # Optional: might be too large? Keep for now.
            "chunks": chunks,
            "content_hash": content_hash
        }
        
        client = _get_client()
        if not client:
            logger.error("Redis client not available for TempDocStore")
            raise RuntimeError("Cache unavailable")

        # Save as JSON string
        await client.set(key, json.dumps(data), ex=ttl)
        return temp_doc_id

    @classmethod
    async def get(cls, tenant_id: str, temp_doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Get raw temp doc data.
        """
        client = _get_client()
        if not client:
            return None
            
        key = cls._key(tenant_id, temp_doc_id)
        raw = await client.get(key)
        if not raw:
            return None
            
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    @classmethod
    async def search(
        cls, 
        tenant_id: str, 
        temp_doc_id: str, 
        query: str, 
        top_k: int = 5
    ) -> Dict[str, Any]:
        """
        Search within a temp doc.
        Returns { "context": str, "citations": list }
        """
        data = await cls.get(tenant_id, temp_doc_id)
        if not data:
            return {"context": "", "citations": []}
            
        chunks = data.get("chunks", [])
        
        # Lexical rank
        top_chunks = lexical_rank(chunks, query, top_k=top_k)
        
        # Build context & citations
        context_parts = []
        citations = []
        
        for c in top_chunks:
            text = c.get("text", "")
            context_parts.append(text)
            
            # Construct citation
            citations.append({
                "chunk_id": f"temp_{c.get('chunk_id')}", # Required by Citation schema
                "snippet": text[:100] + "...",
                "source_url": f"temp://{tenant_id}/{temp_doc_id}#chunk_{c.get('chunk_id')}", # Alias for file_url
                "title": data.get("meta", {}).get("filename", "Temp Doc"),
                "score": 1.0 # Dummy score for temp
            })
            
        return {
            "context": "\n\n...\n\n".join(context_parts),
            "citations": citations,
            "chunks": top_chunks # Expose raw chunks for agent-level merging
        }

    @classmethod
    async def check_quota(cls, tenant_id: str, limit: int = 50, window: int = 3600) -> bool:
        """
        Check if tenant has exceeded upload quota.
        Returns True if allowed, False if exceeded.
        """
        client = _get_client()
        if not client:
            return True # Fail open if cache down? Or fail closed? Fail open for MVP.
            
        key = f"quota:temp_docs:{tenant_id}"
        try:
            # INCR returns the new value
            count = await client.incr(key)
            if count == 1:
                # First time, set expiry
                await client.expire(key, window)
            
            return count <= limit
        except Exception as e:
            logger.error(f"Quota check failed: {e}")
            return True
