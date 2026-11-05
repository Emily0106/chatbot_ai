"""
PII Detection Utility (Phase 1)

Conservative regex patterns for Vietnamese context:
- National ID (CCCD/CMND): 9-12 digits
- Phone: Vietnamese format (0xx or +84)
- Email: Standard pattern

Returns: (contains_pii, pii_types_list)
"""
import re
from typing import Tuple, List

# National ID: 9-12 consecutive digits (with optional separators)
# Conservative: requires word boundary to reduce false positives
NATIONAL_ID_PATTERN = re.compile(r'\b\d{9,12}\b')

# Vietnamese phone: 0xxxxxxxxx (10 digits starting with 0) or +84xxxxxxxxx (9 digits after +84)
# Use negative lookbehind/lookahead to avoid matching as part of national_id
PHONE_PATTERN = re.compile(r'(?:^|(?<=\s)|\+)(0\d{9}|84\d{9})(?=\s|$|[^\d])')

# Email: standard pattern
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')


def detect_pii(text: str) -> Tuple[bool, List[str]]:
    """
    Detect PII in text.
    
    Args:
        text: Input text to scan
        
    Returns:
        Tuple of (contains_pii: bool, pii_types: List[str])
        pii_types can include: "national_id", "phone", "email"
    """
    if not text:
        return False, []
    
    pii_types = []
    
    # Check national ID
    if NATIONAL_ID_PATTERN.search(text):
        pii_types.append("national_id")
    
    # Check phone
    if PHONE_PATTERN.search(text):
        pii_types.append("phone")
    
    # Check email
    if EMAIL_PATTERN.search(text):
        pii_types.append("email")
    
    contains_pii = len(pii_types) > 0
    return contains_pii, pii_types
