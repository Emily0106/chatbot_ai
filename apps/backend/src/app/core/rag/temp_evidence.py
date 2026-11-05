
# apps/backend/src/app/core/rag/temp_evidence.py
import re
from typing import List, Dict, Any, Tuple

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ỹ]{2,}")
_VI_STOP = {
    "là", "và", "của", "cho", "các", "những", "một", "theo", "trong", "khi",
    "với", "được", "tại", "đến", "từ", "về", "này", "đó", "cái", "thì", "mà"
}

def _tokens(s: str) -> List[str]:
    toks = [t.lower() for t in _TOKEN_RE.findall(s or "")]
    return [t for t in toks if t not in _VI_STOP]

def _overlap_count(q_toks: set, t_str: str) -> int:
    t_toks = set(_tokens(t_str))
    if not t_toks:
        return 0
    return sum(1 for x in q_toks if x in t_toks)

def evaluate_temp_chunks(
    chunks: List[Dict[str, Any]],
    query: str,
    *,
    min_overlap: int = 1,
    base_score: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Filter and score temporary chunks based on lexical overlap.
    Returns list of chunks with injected 'score' and 'gate_reason'.
    """
    if not chunks:
        return []

    q_toks = set(_tokens(query))
    if not q_toks:
        # Empty query or only stop words? Return all or none?
        # Return none to be safe against garbage.
        return []

    scored_chunks = []
    
    for ch in chunks:
        text = ch.get("text") or ch.get("chunk_text") or ""
        ov = _overlap_count(q_toks, text)
        
        # Scoring Logic:
        # If strict overlap met: Base + (overlap / len(q)) * boost
        # Cap at 0.95 (Temp docs are slightly less trusty than KB curated?)
        # Actually user wants to use temp docs if they match.
        
        is_pass = False
        score = 0.0
        
        if ov >= min_overlap:
             is_pass = True
             # Boost logic
             boost = min(0.4, (ov / max(1, len(q_toks))) * 0.5)
             score = base_score + boost
        
        if is_pass:
            # Inject score
            ch_out = dict(ch) # shallow copy
            ch_out["score"] = score
            ch_out["gate_reason"] = f"overlap={ov}"
            scored_chunks.append(ch_out)
            
    # Sort desc
    scored_chunks.sort(key=lambda x: x["score"], reverse=True)
    return scored_chunks
