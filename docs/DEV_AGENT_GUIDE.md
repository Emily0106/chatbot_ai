# Hướng dẫn Phát triển Agent (Developer Guide)

**Dự án**: Gov-AI Agent Framework
**Yêu cầu cốt lõi**: Zero-Trust, Fail-Closed, Offline-First.
**Phiên bản**: 1.0

---

## 1. Purpose (Mục đích)

Tài liệu này hướng dẫn lập trình viên phát triển, mở rộng và kiểm thử Agent một cách **an toàn** và **độc lập**.
Chúng tôi thiết kế hệ thống để bạn có thể dev và run test **ngay trên máy cá nhân mà không cần cài đặt Docker, Postgres hay Qdrant**.

Mọi thay đổi commit lên repo bắt buộc phải tuân thủ nghiêm ngặt quy tắc Zero-Trust.

---

## 2. Quick Start (5 minutes)

1.  **Clone Repo & Setup Python Env**:
    ```bash
    git clone <repo-url>
    cd gov-ai
    python3 -m venv venv
    source venv/bin/activate
    pip install -r apps/backend/requirements.txt
    ```

3.  **Authentication (New in B3)**:
    API is now secured. You must send `X-API-Key` header.
    Default Dev Key: `dev-key-123`
    ```bash
    curl -H "X-API-Key: dev-key-123" http://localhost:8000/api/chat ...
    ```

    2.  **Chạy Test Tier-0 (Offline Mode)**:
    Tier-0 chạy "out-of-the-box" ngay sau khi clone, **không cần file .env**.
    ```bash
    # Test tuân thủ contract & logic cơ bản
    python -m pytest apps/backend/src/test_agent_certification.py
    python -m pytest apps/backend/src/test_scaffold_agents.py
    ```

3.  **Tạo Agent mới (Nếu cần)**:
    Copy file mẫu `apps/backend/src/app/agents/citizen_agent.py` sang file mới (vd: `tax_agent.py`) và đổi `agent_id`.

---

## 3. Golden Rules (Zero-Trust)

Đây là các quy tắc "Bất di bất dịch". Vi phạm sẽ block PR ngay lập tức.

1.  **NO Raw Clients**: TUYỆT ĐỐI CẤM import `requests`, `httpx`, `psycopg2`, `asyncpg`, `qdrant_client`, `sqlalchemy` trong file Agent.
    -   *Lý do*: Security audit và connection pooling.
    -   *Giải pháp*: Dùng Wrapper Core (`rag_retrieve`, `sql_execute_safe`, `web_search`).
        -   `from app.core.sql.api import sql_execute_safe`
        -   `from app.core.tools.web import web_search, external_api_call`

2.  **Fail-Closed**: Nếu Agent không tìm thấy thông tin phù hợp -> **Phải từ chối (Refusal)**.
    -   *Cấm*: Bịa đặt câu trả lời (Hallucination) hoặc trả lời chung chung khi không có context.
    -   *Return*: `RefusalCode.NO_EVIDENCE`.

3.  **One Agent = One File**: Toàn bộ logic, metadata, policy của 1 Agent nằm gọn trong 1 file `.py` duy nhất tại `apps/backend/src/app/agents/`.

4.  **Offline First**: Code của bạn phải chạy được Unit Test mà không cần connect DB thật. Mọi IO phải được mock.

---

## 4. Agent Anatomy (Cấu trúc 1 File)

Mỗi Agent file (ví dụ `apps/backend/src/app/agents/my_agent.py`) phải bao gồm:

1.  **Header "AGENT TOOL NOTE"**: Mô tả chức năng và tools sử dụng (để AI Router hiểu).
2.  **Class kế thừa `BaseAgent`**.
3.  **Metadata (`AgentMetadata`)**: Định danh `agent_id`, `name`, và `doc_types`.
4.  **Policy (`AgentPolicy`)**: Quyền hạn `required_clearance`, `required_scopes`.
5.  **Method `process()`**: Logic chính.

```python
"""
AGENT TOOL NOTE
- agent_id: my_agent
- business: Giải đáp thuế thu nhập cá nhân.
- tools: rag_retrieve
"""
from app.agents.base import BaseAgent
from app.agents.contract import AgentMetadata, AgentPolicy, TrustedContext, AgentResponse, RefusalCode

class MyAgent(BaseAgent):
    metadata = AgentMetadata(
        agent_id="my_agent",
        name="Trợ lý Thuế",
        description="Hỗ trợ tra cứu thuế TNCN",
        doc_types=["tax_law", "tax_guideline"]
    )
    
    policy = AgentPolicy(
        required_clearance=1,
        # Optional: Yêu cầu context field bắt buộc (fail-closed nếu thiếu)
        required_context_fields=["geo_code", "department_id"] 
    )

    async def process(self, ctx: TrustedContext, query: str) -> AgentResponse:
        # Import wrapper bên trong hàm để tránh circular dependency
        from app.core.rag.pipeline import rag_retrieve
        # ... logic ...
```

---

## 5. Offline Mode (No DB / No Docker)

Đây là chế độ phát triển **MẶC ĐỊNH**. Bạn không cần Docker hay DB để code logic Agent.

### Cách thức hoạt động
Chúng ta sử dụng `pytest` và `unittest.mock` để giả lập (mock) toàn bộ các tầng IO (RAG, SQL, LLM). Developer chỉ cần viết test case kiểm tra logic xử lý dữ liệu sau khi "nhận được" kết quả từ mock.

### Lệnh chạy (Command)
```bash
# Chạy bộ test Certification (Kiểm tra tuân thủ contract & logic cơ bản)
pytest -q apps/backend/src/test_agent_certification.py -v

# Chạy test logic riêng của agent (Nếu bạn viết thêm)
python3 -m pytest apps/backend/src/test_scaffold_agents.py
```

### Cách viết Test Mock (Ví dụ)
Đây là cách bạn test logic Agent mà không cần Qdrant thật:

```python
# test_my_agent.py
import pytest
from unittest.mock import AsyncMock, patch
from app.agents.registry import registry
from app.agents.contract import TrustedContext

@pytest.mark.asyncio
async def test_my_agent_mocked():
    ctx = TrustedContext(tenant_id="test", user_id="dev", security_level=1)
    
    # Mock RAG trả về kết quả giả định
    mock_rag_res = AsyncMock()
    mock_rag_res.context = "Thuế TNCN là 10%..."
    mock_rag_res.citations = [{"source": "Luật Thuế"}]
    
    # Mock LLM trả về câu trả lời
    mock_llm_res = "Dựa vào văn bản, thuế là 10%."

    # Patch các hàm Core Wrapper
    with patch("app.core.rag.pipeline.rag_retrieve", return_value=mock_rag_res) as mock_retrieve, \
         patch("app.core.llm_client.achat", return_value=mock_llm_res):
         
        agent = registry.get("my_agent")
        resp = await agent.process(ctx, "Thuế bao nhiêu?")
        
        # Assert logic
        assert resp.answer == mock_llm_res
        assert len(resp.citations) == 1
        # Verify Agent đã gọi RAG đúng filter chưa
        call_args = mock_retrieve.call_args[1]
        assert "tax_law" in call_args["filters"].doc_types
```

---

## 6. How To Add Logic Safely

Khi cần Agent thông minh hơn, hãy thêm logic theo các pattern an toàn sau:

### 6.1. RAG-Only (Cơ bản)
Chỉ cần gọi `rag_retrieve` và truyền đúng `filters`.

```python
from app.core.rag.pipeline import rag_retrieve

# ... trong process() ...
rag_res = await rag_retrieve(
    db=db,
    tenant_id=ctx.tenant_id,
    query=query,
    filters=RetrievalFilters(doc_types=self.metadata.doc_types), # Quan trọng
    security_level=ctx.security_level
)
```

### 6.2. SQL Query (Dữ liệu cấu trúc)
Dùng `sql_execute_safe`. Agent không được viết câu SQL raw string nếu không cần thiết, tốt nhất là gọi qua Template hoặc Builder.

```python
from app.core.sql.api import sql_execute_safe

# ...
rows = await sql_execute_safe(
    sql="SELECT * FROM structured_rows WHERE doc_category = :cat AND data_content->>'code' = :code",
    params={"cat": "tax_code", "code": "123"},
    tenant_id=ctx.tenant_id
)
```
*Lưu ý: Test Offline phải mock `sql_execute_safe`.*

### 6.3. Web Search (Internet)
Dùng `web_search` wrapper. Kết quả search phải được coi là context cho LLM.
*Lưu ý: Hàm này hiện là stub, BẮT BUỘC phải mock trong Tier-0.*

```python
from app.core.tools.web import web_search

# ...
search_res = await web_search(query, num_results=3)
context = "\n".join([r.snippet for r in search_res])
# Sau đó đưa context vào prompt LLM (achat)
```

### 6.4. External API (Gọi bên thứ 3)
Dùng `external_api_call`. Không dùng `requests.get`.
*Lưu ý: Hàm này hiện là stub, BẮT BUỘC phải mock trong Tier-0.*

```python
from app.core.tools.web import external_api_call

# ...
res = await external_api_call(
    method="GET",
    url="https://api.gdt.gov.vn/status",
    allow_list_check=True # Bắt buộc
)
```

---

## 7. Refusal & Evidence Rules

Agent **BẮT BUỘC** phải từ chối nếu không đủ thông tin. Code mẫu:

```python
# 1. Check RAG Result
if not rag_res or not rag_res.context:
    return self._make_refusal(
        code=RefusalCode.NO_EVIDENCE,
        message="Xin lỗi, tôi không tìm thấy văn bản pháp luật liên quan."
    )

# 2. Check LLM Refusal (nếu LLM tự nhận thấy không trả lời được)
if "I cannot answer" in llm_answer: 
    return self._make_refusal(RefusalCode.OUT_OF_SCOPE, "Câu hỏi ngoài phạm vi.")
```

---

## 8. Testing Playbook (Offline First)

Chúng ta chia Test thành 3 tầng (Tiers):

### Tier 0: Mandatory Offline (Bắt buộc)
- **Môi trường**: Local máy dev (Không Docker, Không DB).
- **Lệnh**: `pytest apps/backend/src/test_agent_certification.py`
- **Mục tiêu**: Đảm bảo Agent không import bậy, Metadata đúng, Logic Fail-closed hoạt động (với mock).

### Tier 1: Optional Mocked Integration
- **Môi trường**: Local máy dev.
- **Lệnh**: `pytest apps/backend/tests/integration/test_agent_flow_mock.py`
- **Mục tiêu**: Test luồng phức tạp hơn (Agent A gọi Agent B) nhưng vẫn mock DB.

### Tier 2: True E2E (Chỉ dành cho Maintainer)
- **Môi trường**: Có Docker + API Key thật.
- **Lệnh**: `./scripts/run_e2e_true.sh`
- **Cảnh báo**: **Không yêu cầu Tier 2 để merge PR agent logic.** Tier 2 thường flaky và chỉ chạy nightly trên CI server.

### Full Monorepo Suite (Recommended)
- **Môi trường**: Local máy dev.
- **Lệnh**: `./scripts/run_all_tests.sh`
- **Mục tiêu**: Chạy toàn bộ Unit test (Backend + Ingestion) và Security E2E với cấu hình PYTHONPATH chuẩn.

---

## 9. PR Checklist (GitLab)

Trước khi tạo Merge Request, hãy tự tick checklist này:

- [ ] Agent nằm trong 1 file `.py` duy nhất.
- [ ] Header `AGENT TOOL NOTE` đã được cập nhật đúng với logic code.
- [ ] Không có forbidden imports (`requests`, `psycopg2`...).
- [ ] Chạy pass `test_agent_certification.py` (Tier 0).
- [ ] Logic Refusal (`NO_EVIDENCE`) đã được handle.
- [ ] Không hardcode API Key hay Secrets.

---

## 10. Troubleshooting

| Lỗi | Nguyên nhân | Giải pháp |
| :--- | :--- | :--- |
| **`ImportError: No module named 'requests'`** | Bạn đang cố import thư viện cấm. | Xóa import đó. Sử dụng Wrapper trong `app.core` hoặc `app.utils`. |
| **`ValueError: Agent missing metadata`** | Class Agent thiếu biến `metadata`. | Định nghĩa `metadata = AgentMetadata(...)`. |
| **`ConnectionRefusedError` khi chạy test** | Bạn quên mock DB/RAG và test đang cố gọi thật. | Dùng `unittest.mock.patch` cho các hàm wrapper. Xem mục 5. |
| **Test certification fail "Tool Note missing"** | Thiếu comment block đầu file. | Thêm `AGENT TOOL NOTE` vào dòng đầu tiên. |
| **Rerank Timeout / Event Loop Closed** | Lỗi infra khi chạy Tier 2 E2E. | Bỏ qua Tier 2, chỉ cần Tier 0 pass là để Review. |

---

## 11. Appendix (Examples)

*(Xem file `apps/backend/src/app/agents/citizen_agent.py` để thấy code mẫu hoàn chỉnh)*
