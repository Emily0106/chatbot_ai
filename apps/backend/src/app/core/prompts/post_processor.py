"""Post-processing to enforce response structure and limits."""
import re
from typing import Any, Dict, Tuple


def enforce_max_questions(
    answer: str, max_questions: int = 2
) -> Tuple[str, Dict[str, Any]]:
    """
    Enforce max questions WITHIN section (not truncating entire text).
    
    Returns: (processed_answer, metadata)
    """

    # Find section 3 (HỎI LÀM RÕ) between headers
    section_pattern = re.compile(
        r"(3\.\s*HỎI LÀM RÕ.*?)(4\.\s*KẾ HOẠCH HÀNH ĐỘNG)",
        re.DOTALL | re.IGNORECASE,
    )

    match = section_pattern.search(answer)
    if not match:
        return answer, {
            "question_count": None,
            "was_truncated": False,
            "reason": "no_clarify_section",
        }

    clarify_section = match.group(1)
    next_header = match.group(2)

    # Find question lines (lines with ?)
    lines = clarify_section.splitlines()
    question_lines = [ln for ln in lines if "?" in ln]
    question_count = len(question_lines)

    if question_count <= max_questions:
        return answer, {"question_count": question_count, "was_truncated": False}

    # Keep section structure, just limit question lines
    kept_q_count = 0
    new_lines = []

    for ln in lines:
        if "?" in ln:
            if kept_q_count < max_questions:
                new_lines.append(ln)
                kept_q_count += 1
            # Skip question lines beyond limit
        else:
            new_lines.append(ln)  # Keep non-question lines (headers, etc.)

    new_clarify = "\n".join(new_lines)
    new_answer = (
        answer[: match.start(1)]
        + new_clarify
        + "\n"
        + next_header
        + answer[match.end(2) :]
    )

    return new_answer, {
        "question_count": question_count,
        "was_truncated": True,
        "kept": max_questions,
    }


def validate_response_structure(answer: str) -> Dict[str, bool]:
    """Check if response follows 4-part template."""

    checks = {
        "has_context_restate": bool(
            re.search(r"(?:1\.|NHẮC LẠI|BỐI CẢNH)", answer, re.I)
        ),
        "has_classification": bool(
            re.search(r"(?:2\.|PHÂN LOẠI|LĨNH VỰC)", answer, re.I)
        ),
        "has_clarify": bool(re.search(r"(?:3\.|HỎI LÀM RÕ)", answer, re.I)),
        "has_action_plan": bool(
            re.search(r"(?:4\.|KẾ HOẠCH HÀNH ĐỘNG|\[ \])", answer, re.I)
        ),
    }

    checks["valid"] = all(checks.values())

    return checks
