from __future__ import annotations
import re
import unicodedata
from pathlib import Path

def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize a filename to be safe for local filesystem storage.
    - Normalizes Unicode (NFKD) to strip accents/weird markers if needed,
      but here we try to keep UTF-8 chars if filesystem supports it,
      while stripping dangerous chars.
    - Removes path traversal characters (.., /, \).
    - Truncates to max_length.
    """
    # 1. Strip path and get basename
    name = Path(filename).name

    # 2. Normalize unicode characters (optional: strict ASCII vs keep UTF8)
    # Strategy: Keep allowed UTF-8, strip control chars.
    # Allow: letters, numbers, dot, dash, underscore, spaces (maybe)
    # Disallow: / \ : * ? " < > |
    
    # Simple regex whitelist approach is safest for cross-platform (Windows/Linux)
    # Allow alphanumeric (including unicode letters), space, dot, dash, underscore.
    
    # But first, normalize to compose characters
    name = unicodedata.normalize('NFC', name)
    
    # Replace dangerous chars with _
    # Windows forbidden: < > : " / \ | ? *
    # Control chars: 0-31
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    
    # Stripping leading/trailing dots/spaces (Windows issue)
    name = name.strip(' .')
    
    # Ensure it's not empty, fallback to default
    if not name:
        name = "unnamed_file"

    # Truncate
    if len(name.encode('utf-8')) > max_length:
        # naive truncate, might break multibyte char at end but FS handles it or valid utf8 check needed
        # safe approach: truncate string len
        name = name[:max_length]
        
    return name
