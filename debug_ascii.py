
import unicodedata
import re

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+", re.UNICODE)

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

test_str = "ngơời b"
print(f"Testing: '{test_str}'")
res = ascii_norm(test_str)
print(f"Result ascii_norm: '{res}'")
