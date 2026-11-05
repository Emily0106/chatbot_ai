"""Prompt templates with retrieval/generation separation."""
from typing import Optional

from app.core.memory.case_memory import CaseMemory


def build_retrieval_context(user_message: str, case: Optional[CaseMemory]) -> str:
    """
    Build SHORT context for retrieval query.
    
    This augments the user message with MINIMAL context to avoid
    polluting vector/lexical search.
    
    Returns: "user message. Bối cảnh: tai nghe, trùng mẫu mã"
    """
    if not case:
        return user_message

    summary = case.get_short_summary()
    if not summary:
        return user_message

    return f"{user_message}. Bối cảnh: {summary}"


def build_generation_prompt(
    user_message: str,
    case: Optional[CaseMemory],
    context: str,  # Retrieved evidence from RAG
    max_questions: int = 2,
) -> str:
    """
    Build FULL structured prompt for LLM generation.
    
    This is the system/user message that goes to LLM, NOT to retrieval.
    """

    # Build case context section
    case_context = ""
    if case and (case.entities or case.claim_raw_phrase):
        entity_parts = []
        if case.entities.get("product"):
            entity_parts.append(f"Sản phẩm: {case.entities['product']}")
        if case.claim_raw_phrase:
            entity_parts.append(f"Vấn đề: {case.claim_raw_phrase}")

        if entity_parts:
            case_context = f"""
BỐI CẢNH TỪ LƯỢT TRƯỚC:
{chr(10).join(f"- {part}" for part in entity_parts)}
"""

    # Build full prompt
    prompt = f"""Bạn là chuyên gia tư vấn pháp lý về Sở hữu Trí tuệ.

Câu hỏi: {user_message}
{case_context}

TÀI LIỆU THAM KHẢO:
{context}

YÊU CẦU CẤU TRÚC TRẢ LỜI (BẮT BUỘC):

1. NHẮC LẠI BỐI CẢNH (1 câu):
   {_get_context_instruction(case)}

2. PHÂN LOẠI LĨNH VỰC (1-2 lĩnh vực chính):
   - Ưu tiên "kiểu dáng công nghiệp" nếu về mẫu mã/thiết kế/ngoại hình
   - Chỉ nhắc "nhãn hiệu" nếu rõ ràng về logo/tên/brand
   - Dùng điều kiện: "có thể", "tùy vào"

3. HỎI LÀM RÕ (TỐI ĐA {max_questions} câu):
   - Chỉ hỏi thông tin ảnh hưởng phân loại/xử lý
   - VD: "Có văn bằng bảo hộ kiểu dáng không?"

4. KẾ HOẠCH HÀNH ĐỘNG (5-7 bước checklist):
   [ ] Thu thập chứng cứ (ảnh sản phẩm, quảng cáo)
   [ ] Tra cứu cơ sở dữ liệu SHTT
   [ ] So sánh mức độ tương tự
   [ ] Đánh giá rủi ro pháp lý
   [ ] Chuẩn bị phương án (redesign/license/đáp trả)

QUAN TRỌNG:
- KHÔNG bịa số liệu/mức phạt nếu không có nguồn
- KHÔNG hỏi quá {max_questions} câu
- LUÔN trả lời phần chắc chắn + next action

QUY TẮC PHÂN LOẠI CHỐNG DRIFT:
1. "Mẫu mã / thiết kế / ngoại hình" → KIỂU DÁNG CÔNG NGHIỆP
2. "Logo / tên / brand / nhãn" → NHÃN HIỆU
3. "Công nghệ / kỹ thuật" → SÁNG CHẾ
4. "Văn học / phần mềm / âm nhạc" → BẢN QUYỀN
"""

    return prompt


def _get_context_instruction(case: Optional[CaseMemory]) -> str:
    """Generate context restatement instruction."""
    if case and case.claim_raw_phrase:
        return f'Tóm tắt ngắn về "{case.claim_raw_phrase}"'
    return "Xác nhận chủ đề câu hỏi"
