"""Case memory structure for conversation context."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional


@dataclass
class CaseMemory:
    """Single conversation case with entities and claims."""

    id: str
    session_id: str
    topic: str
    user_goal: str

    # Entities
    entities: Dict[str, str] = field(default_factory=dict)

    # Claim - keep raw Vietnamese phrases
    claim_type: Optional[
        Literal[
            "industrial_design_candidate",
            "trademark_candidate",
            "patent_candidate",
            "copyright_candidate",
        ]
    ] = None
    claim_raw_phrase: str = ""  # e.g., "trùng mẫu mã", "giống logo"

    # Knowledge state
    known_facts: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_updated_turn: int = 0
    last_message: str = ""

    def update_from_message(self, message: str, turn: int):
        """Extract entities/claims and update metadata."""
        self.last_message = message
        self.last_updated_turn = turn
        self.updated_at = datetime.utcnow()
        self._extract_entities_and_claims(message)

    def _extract_entities_and_claims(self, message: str):
        """Extract entities and claims with raw phrase preservation."""
        msg_lower = message.lower()

        # Product entities
        products = ["tai nghe", "điện thoại", "laptop", "áo", "giày", "túi xách"]
        for product in products:
            if product in msg_lower:
                self.entities["product"] = product
                break

        # Claim detection - PRIORITIZE industrial design
        design_phrases = [
            ("trùng mẫu mã", "industrial_design_candidate"),
            ("giống thiết kế", "industrial_design_candidate"),
            ("tương tự ngoại hình", "industrial_design_candidate"),
            ("sao chép kiểu dáng", "industrial_design_candidate"),
            ("giống hình dạng", "industrial_design_candidate"),
        ]

        for phrase, claim_type in design_phrases:
            if phrase in msg_lower:
                self.claim_type = claim_type
                self.claim_raw_phrase = phrase
                return  # Industrial design has priority

        # Trademark (only if NOT design)
        trademark_phrases = [
            ("trùng logo", "trademark_candidate"),
            ("giống nhãn hiệu", "trademark_candidate"),
            ("tên thương hiệu", "trademark_candidate"),
        ]

        for phrase, claim_type in trademark_phrases:
            if phrase in msg_lower:
                self.claim_type = claim_type
                self.claim_raw_phrase = phrase
                return

    def get_short_summary(self) -> str:
        """
        Generate SHORT summary for retrieval query augmentation.
        
        Returns: "tai nghe, trùng mẫu mã" or empty string.
        """
        parts = []
        if self.entities.get("product"):
            parts.append(self.entities["product"])
        if self.claim_raw_phrase:
            parts.append(self.claim_raw_phrase)
        return ", ".join(parts)
