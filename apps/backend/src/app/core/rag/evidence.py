
from dataclasses import dataclass, field
from typing import List, Optional, Any

@dataclass
class EvidenceItem:
    chunk_id: str
    text: str
    score: float
    payload: dict
    
    @property
    def source_uri(self) -> str:
        # Check standard fields: file_url, source_url, or construct from doc meta
        return self.payload.get("file_url") or self.payload.get("source_url") or ""

@dataclass
class GateDecision:
    status: str  # "pass", "refuse", "handoff"
    reason: str
    target_agent: Optional[str] = None

class EvidenceGate:
    def evaluate(self, chunks: List[dict]) -> GateDecision:
        if not chunks:
            return GateDecision("refuse", "No documents found.")
        
        # 1. Convert to Items
        items = [
            EvidenceItem(
                chunk_id=str(c.get("chunk_id")),
                text=c.get("chunk_text") or c.get("display_text") or "",
                score=float(c.get("score", 0.0)),
                payload=c.get("payload", {})
            ) 
            for c in chunks
        ]
        
        # 2. Sort by score desc (Defensive)
        items = sorted(items, key=lambda x: x.score, reverse=True)
        best = items[0]
        
        # 3. Rule: Citation Integrity Check (Fail Safe)
        # Any top answer MUST have a source.
        if not best.source_uri:
             return GateDecision("refuse", "Top evidence lacks citation source.")

        # 4. Rule: Score Threshold (RRF Aware)
        # Check score kind from payload (set by db_vector or previous steps)
        kind = str(best.payload.get("_score_kind") or "cosine").lower()
        
        # RRF scores are small (~0.01), so we skip absolute threshold check if RRF.
        # But we still require citation integrity (checked above).
        if "rrf" in kind or "fused" in kind:
             pass # RRF is relative, trust the sort + integrity
        else:
             # Cosine/Dense/Sparse -> Enforce threshold
             # Gov-grade safe threshold: 0.4
             if best.score < 0.4:  
                return GateDecision("refuse", f"Low confidence evidence (score={best.score:.2f}, kind={kind})")

        return GateDecision("pass", "Evidence sufficient.")
