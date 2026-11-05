
import unicodedata
import re

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
    "ngơời": "nguoi", # Explicitly adding the one from the curl command just in case
}

def normalize_query_basic(s: str) -> str:
    """Normalize unicode and basic spacing."""
    s = (s or "").strip()
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"\s+", " ", s)
    return s

def normalize_query_for_router(s: str) -> str:
    s2 = normalize_query_basic(s).lower()
    
    print(f"Input normalized: '{s2}'")
    print(f"Hex: {[hex(ord(c)) for c in s2]}")
    
    # fix common typos
    for k, v in _COMMON_FIX.items():
        if k in s2:
            print(f"Match found for key: '{k}' -> '{v}'")
            s2 = s2.replace(k, v)
            
    s2 = re.sub(r"[\:\,\.\;\(\)\[\]\{\}]+", " ", s2)
    s2 = re.sub(r"\s+", " ", s2).strip()
    return s2

test_str = "ngơời b"
print(f"Testing: '{test_str}'")
res = normalize_query_for_router(test_str)
print(f"Result: '{res}'")
