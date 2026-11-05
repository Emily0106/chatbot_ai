# app/core/llm.py
from __future__ import annotations

from typing import AsyncGenerator, Dict, List, Optional

from openai import AsyncOpenAI

from app.config import settings


def _get(name: str, default=None):
    return getattr(settings, name, default)


def _client() -> AsyncOpenAI:
    api_key = _get("OPENAI_API_KEY")
    base_url = _get("OPENAI_BASE_URL")
    timeout = float(_get("OPENAI_TIMEOUT", 60))
    max_retries = int(_get("OPENAI_MAX_RETRIES", 2))

    if not api_key and not base_url:
        # base_url co the truyen khi dung gateway noi bo; neu ca 2 deu thieu thi coi nhu chua set
        raise RuntimeError("Missing OPENAI_API_KEY (hoac OPENAI_BASE_URL).")

    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


# init 1 lan
_client_instance = _client()


async def generate_text(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Chat completion non-stream.
    Dung cho: Text-to-SQL, tom tat, rut trich...
    """
    model = model or _get("OPENAI_MODEL_NAME", "gpt-4o-mini")
    resp = await _client_instance.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )
    return (resp.choices[0].message.content or "").strip()


async def generate_stream(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.3,
) -> AsyncGenerator[str, None]:
    """
    Chat completion stream.
    """
    model = model or _get("OPENAI_MODEL_NAME", "gpt-4o-mini")
    stream = await _client_instance.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            yield content


# Global cache for local model
_local_embedder = None

async def embed_texts(
    texts: List[str],
    *,
    model: Optional[str] = None,
) -> List[List[float]]:
    """
    Embeddings cho vector search.
    Support: OpenAI or Local (SentenceTransformer)
    """
    if not texts:
        return []

    backend = _get("EMBEDDING_BACKEND", "openai")
    
    if backend == "local":
        global _local_embedder
        model_path = _get("EMBED_MODEL_PATH")
        if not model_path:
            raise RuntimeError("EMBEDDING_BACKEND=local but EMBED_MODEL_PATH is not set")
            
        if _local_embedder is None:
            # Lazy load
            from sentence_transformers import SentenceTransformer
            import asyncio
            # Run load in thread to avoid blocking async loop
            def _load():
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
                print(f"Loading local embedding model on {device}...")
                return SentenceTransformer(model_path, device=device)
            _local_embedder = await asyncio.to_thread(_load)
            
        # Run encode in thread
        import asyncio
        def _encode():
            return _local_embedder.encode(texts).tolist()
        return await asyncio.to_thread(_encode)

    # Default: OpenAI
    model = model or _get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    dimensions = int(_get("OPENAI_EMBEDDING_DIMENSIONS", 1536))
    
    # Only text-embedding-3 models support dimensions
    if "text-embedding-3" in model:
        resp = await _client_instance.embeddings.create(model=model, input=texts, dimensions=dimensions)
    else:
        resp = await _client_instance.embeddings.create(model=model, input=texts)
        
    return [item.embedding for item in resp.data]


async def achat(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 700,
) -> str:
    """Wrapper matching router expectation: achat(messages, temperature, max_tokens)"""
    return await generate_text(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
