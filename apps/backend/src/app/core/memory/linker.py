"""Case linking heuristics for conversation continuity."""
from typing import List, Optional, Tuple

from .case_memory import CaseMemory


def choose_best_case(
    message: str, recent_cases: List[CaseMemory], threshold: float = 0.4
) -> Tuple[Optional[CaseMemory], float, str]:
    """
    Match against TOP-K recent cases, not just active case.
    
    Returns: (best_case|None, score, reason)
    """
    if not recent_cases:
        return None, 0.0, "no_cases"

    best_case = None
    best_score = 0.0
    best_reason = ""

    for case in recent_cases:
        score, reason = score_message_to_case(message, case)
        if score > best_score:
            best_score = score
            best_case = case
            best_reason = reason

    if best_score >= threshold:
        return best_case, best_score, best_reason

    return None, best_score, f"below_threshold({best_reason})"


def score_message_to_case(message: str, case: CaseMemory) -> Tuple[float, str]:
    """Score message similarity to case."""
    score = 0.0
    reasons = []

    msg_lower = message.lower()
    case_msg_lower = case.last_message.lower()

    # 1. Co-reference detection
    coreference_phrases = [
        "đang nói về",
        "vậy còn",
        "tại sao",
        "ngoài ra",
        "cái đó",
        "như này",
        "thế còn",
        "còn gì nữa",
        "ở trên",
        "câu vừa rồi",
        "vấn đề này",
    ]
    if any(phrase in msg_lower for phrase in coreference_phrases):
        score += 0.4
        reasons.append("coreference")

    # 2. Entity overlap
    for entity_key, entity_value in case.entities.items():
        if entity_value and entity_value.lower() in msg_lower:
            score += 0.3
            reasons.append(f"entity:{entity_key}")

    # 3. Same intent/domain
    intent_pairs = [
        ("vi phạm", "domain_identify"),
        ("xử lý", "resolution"),
        ("thủ tục", "procedure"),
        ("mức phạt", "penalty"),
    ]
    for keyword, intent in intent_pairs:
        if keyword in msg_lower and keyword in case_msg_lower:
            score += 0.2
            reasons.append(f"intent:{intent}")
            break

    # 4. Return-to-topic cues
    return_cues = ["quay lại", "tiếp chuyện", "về cái", "trở lại"]
    if any(cue in msg_lower for cue in return_cues):
        score += 0.15
        reasons.append("return_to_topic")

    # 5. Penalize explicit topic switch
    if _is_topic_switch(msg_lower):
        score -= 0.5
        reasons.append("topic_switch_detected")

    reason_str = ",".join(reasons) if reasons else "low_similarity"
    return score, reason_str


def _is_topic_switch(msg_lower: str) -> bool:
    """
    Detect EXPLICIT topic switch.
    
    Removed "ngoài ra" to avoid conflict with coreference.
    """
    switch_keywords = [
        "chuyển sang",
        "hỏi khác",
        "câu hỏi mới",
        "bỏ qua",
        "không nói về",
    ]

    if any(kw in msg_lower for kw in switch_keywords):
        return True

    # Special case: registration vs infringement
    if "thủ tục đăng ký" in msg_lower and "vi phạm" not in msg_lower:
        return True

    return False
