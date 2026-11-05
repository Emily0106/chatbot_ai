
from typing import Optional

class HandoffRouter:
    @staticmethod
    def route(query: str, current_agent: str) -> Optional[str]:
        q = query.lower()
        
        # Rule 1: Legal Intent -> Legal Agent
        # Keywords: luật, nghị định, thông tư, quyết định, hiến pháp...
        if current_agent != "legal_agent":
            if any(k in q for k in ["luật", "nghị định", "thông tư", "hiến pháp", "pháp lệnh"]):
                return "legal_agent"

        # Rule 2: Meeting Intent -> Meeting Agent
        # Keywords: biên bản, cuộc họp, lịch họp, chỉ đạo, kết luận cuộc họp
        if current_agent != "meeting_agent":
            if any(k in q for k in ["biên bản", "cuộc họp", "lịch họp", "kết luận cuộc họp"]):
                return "meeting_agent"

        return None
