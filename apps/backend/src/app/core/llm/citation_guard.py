from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# Strict form: [SOURCE 12]
_STRICT_CITE_RE = re.compile(r"\[source\s+(\d{1,3})\]", re.IGNORECASE)

# Loose block: [SOURCE 1, 2] / [Nguồn 1-3] / [source: 2]
_LOOSE_BLOCK_RE = re.compile(r"\[(?:source|nguồn)[^\]]*\]", re.IGNORECASE)


@dataclass(frozen=True)
class CitationGuardConfig:
    max_repair_rounds: int = 1
    require_any_citation_if_sources_exist: bool = True
    forbid_out_of_range: bool = True
    expand_ranges: bool = False           # if True: "1-3" -> 1,2,3
    max_expand_span: int = 10             # safety cap


def _expand_range(a: int, b: int, max_span: int) -> List[int]:
    if a == b:
        return [a]
    lo, hi = (a, b) if a < b else (b, a)
    if hi - lo > max_span:
        # too wide -> don't expand, return endpoints only
        return [lo, hi]
    return list(range(lo, hi + 1))


def extract_citations(text: str, *, cfg: CitationGuardConfig | None = None) -> List[int]:
    """
    Supports:
      - [SOURCE 1]
      - [SOURCE 1, 2]
      - [Nguồn 1-3]
    Default: does NOT expand ranges unless cfg.expand_ranges=True.
    """
    if not text:
        return []

    cfg = cfg or CitationGuardConfig()
    ids: List[int] = []

    # 1) Loose blocks: parse numbers in any [source/nguồn ...] bracket
    for block in _LOOSE_BLOCK_RE.findall(text):
        nums = re.findall(r"\d{1,3}", block)
        # Handle simple ranges like "1-3" (optional)
        if cfg.expand_ranges:
            ranges = re.findall(r"(\d{1,3})\s*-\s*(\d{1,3})", block)
            for a, b in ranges:
                ids.extend(_expand_range(int(a), int(b), cfg.max_expand_span))
        ids.extend(int(n) for n in nums)

    # 2) Strict form (extra safety)
    for m in _STRICT_CITE_RE.finditer(text):
        ids.append(int(m.group(1)))

    # unique + sorted
    return sorted(set(ids))


def validate_citations(
    answer: str,
    *,
    num_sources: int,
    cfg: CitationGuardConfig | None = None
) -> Tuple[bool, Dict[str, Any]]:
    cfg = cfg or CitationGuardConfig()
    cites = extract_citations(answer, cfg=cfg)

    if num_sources <= 0:
        return True, {"ok": True, "reason": "no_sources_available", "citations": cites}

    if cfg.require_any_citation_if_sources_exist and len(cites) == 0:
        return False, {"ok": False, "reason": "missing_citations", "citations": cites, "num_sources": num_sources}

    if cfg.forbid_out_of_range:
        bad = [c for c in cites if c < 1 or c > num_sources]
        if bad:
            return False, {"ok": False, "reason": "out_of_range", "bad": bad, "citations": cites, "num_sources": num_sources}

    return True, {"ok": True, "reason": "ok", "citations": cites, "num_sources": num_sources}


def make_repair_messages(
    *,
    original_messages: List[Dict[str, str]],
    bad_answer: str,
    num_sources: int
) -> List[Dict[str, str]]:
    repair = f"""
Bạn vừa trả lời nhưng trích dẫn chưa đạt yêu cầu.

YÊU CẦU SỬA:
- Bắt buộc thêm trích dẫn dạng [SOURCE i] cho các ý quan trọng.
- Chỉ được dùng i trong khoảng 1..{num_sources}.
- Không thêm thông tin không có trong CONTEXT.
- Trả về bản trả lời cuối cùng đã sửa.
""".strip()

    return list(original_messages) + [
        {"role": "assistant", "content": bad_answer},
        {"role": "user", "content": repair},
    ]
