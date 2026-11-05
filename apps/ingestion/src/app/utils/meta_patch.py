# apps/ingestion/src/app/utils/meta_patch.py
from dataclasses import is_dataclass, replace
from typing import Any, Dict

def with_meta_updates(meta: Any, updates: Dict[str, Any]) -> Any:
    """
    Return a copy of meta with updates applied, handling Pydantic (v1/v2), 
    dataclasses, or mutable objects.
    """
    # Pydantic v2
    if hasattr(meta, "model_copy"):
        return meta.model_copy(update=updates)
    
    # Pydantic v1
    if hasattr(meta, "copy"):
        return meta.copy(update=updates)
    
    # dataclass
    if is_dataclass(meta):
        try:
            return replace(meta, **updates)
        except TypeError:
            # If field doesn't exist in dataclass definition
            pass

    # fallback (mutable objects or if replace failed)
    try:
        for k, v in updates.items():
            setattr(meta, k, v)
        return meta
    except Exception:
        # If frozen and no copy/replace method worked, return original
        return meta

def with_lane(meta: Any, lane: str) -> Any:
    """
    Deprecated: Use with_meta_updates instead.
    Kept for compatibility during refactor.
    """
    return with_meta_updates(meta, {"ingest_lane": lane})
