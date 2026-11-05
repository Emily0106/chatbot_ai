from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List

_SPACES = re.compile(r"\s+", re.UNICODE)
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)

# domain keywords (bạn có thể mở rộng dần)
DEFAULT_KEYWORDS = [
    "tiêm chủng", "tiem chung",
    "địa chính", "dia chinh",
    "xây dựng", "xay dung",
    "tư pháp", "tu phap",
    "hộ tịch", "ho tich",
    "y tế", "y te",
    "tiếp dân", "tiep dan",
]

def normalize_nfc(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = s.strip()
    return s

def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", s)

def ascii_norm(s: str) -> str:
    """Lower + remove accents + collapse spaces + remove punctuation."""
    s = normalize_nfc(s)
    s = strip_accents(s).lower()
    s = _NON_WORD.sub(" ", s)
    s = _SPACES.sub(" ", s).strip()
    return s

def build_search_text_ascii(*parts: str) -> str:
    """Concat nhiều field -> 1 chuỗi search bỏ dấu."""
    joined = " ".join([p for p in parts if p])
    return ascii_norm(joined)

def extract_keywords_ascii(text: str, *, keywords: Iterable[str] = DEFAULT_KEYWORDS) -> List[str]:
    """
    Trích keyword dựa trên list từ khóa domain.
    Trả về dạng ascii_norm để match ổn định.
    """
    t = ascii_norm(text)
    out: List[str] = []
    for kw in keywords:
        k = ascii_norm(kw)
        if k and k in t:
            out.append(k)
    # unique giữ thứ tự
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq

_COMMON_FIX = {
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngờoi": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    "ngời": "nguoi",
    # Common typos
    "nguoi": "nguoi",
    "nguòi": "nguoi",
    "ngươi": "nguoi",
    "nguoi": "nguoi",
    "cccd": "cccd",
    "c.c.c.d": "cccd",
    "c.c.c.d.": "cccd",
    "cccd:": "cccd",
    # Specific typo from curl test
    "ngơời": "nguoi",
}

def normalize_query_basic(s: str) -> str:
    """Normalize unicode and basic spacing."""
    s = (s or "").strip()
    s = unicodedata.normalize("NFC", s)
    s = _SPACES.sub(" ", s)
    return s

def normalize_query_for_router(s: str) -> str:
    """
    Tier 0 normalization:
    - Lowercase
    - Fix common typos (ngơời -> nguoi)
    - Normalize punctuation
    """
    s2 = normalize_query_basic(s).lower()
    
    # fix common typos
    for k, v in _COMMON_FIX.items():
        if k in s2:
            s2 = s2.replace(k, v)
            
    # normalize punctuation around tokens (cccd:, cccd.)
    s2 = re.sub(r"[\:\,\.\;\(\)\[\]\{\}]+", " ", s2)
    s2 = _SPACES.sub(" ", s2).strip()
    return s2
