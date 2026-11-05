from __future__ import annotations
import re
import unicodedata

def vi_norm(s: str) -> str:
    """
    Normalize Vietnamese string for accent-insensitive search:
    - Lowercase
    - Remove accents (NFD -> ASCII)
    - Replace 'đ' -> 'd'
    - Normalize whitespace
    """
    if not s:
        return ""
    
    s = s.strip().lower()
    
    # Handle specifically Vietnamese 'đ' which NFD usually misses or handles differently
    s = s.replace("đ", "d")
    
    # Normalize unicode characters to NFD (decomposed)
    s = unicodedata.normalize("NFD", s)
    
    # Strip combining diacritical marks
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    
    return s
