# apps/ingestion/src/app/utils/route_pdf.py
from typing import Tuple, Dict, Any
from app.core.config import GovConfig

def decide_pdf_lane(sniff: Dict[str, Any]) -> Tuple[str, str]:
    # returns (lane, reason)
    if sniff.get("is_encrypted"):
        return ("reject", "encrypted_pdf")

    # hard safety
    if sniff.get("page_count", 0) > GovConfig.MAX_PAGE_COUNT:
        return ("reject", "page_limit_exceeded")

    # auto mode rule
    if sniff.get("has_text_layer") and sniff.get("page_count", 0) <= GovConfig.FAST_LANE_MAX_PAGES and sniff.get("text_density", 0) >= GovConfig.FAST_LANE_MIN_DENSITY:
        return ("fast", "digital_short")

    return ("heavy", "scan_or_long_or_low_density")
