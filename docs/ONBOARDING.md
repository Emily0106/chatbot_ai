# Tài liệu Onboarding (Gov-AI Agent Framework)

Chào mừng bạn đến với dự án **Gov-AI Agent Framework**. Tài liệu này cung cấp toàn bộ thông tin cần thiết để bạn hiểu hệ thống, thiết lập môi trường và bắt đầu đóng góp code một cách an toàn (Zero-Trust).

## 1. Mục tiêu & Triết lý

Hệ thống được thiết kế để phục vụ Chính phủ điện tử với các tiêu chuẩn khắt khe:
- **Zero-Trust**: Mặc định không tin tưởng đầu vào, output của LLM, hay các service bên ngoài. Mọi thứ phải được kiểm chứng (Evidence-based).
- **Fail-Closed**: Nếu hệ thống không tìm thấy dữ liệu hoặc gặp lỗi, agent phải từ chối trả lời (refusal) thay vì bịa đặt (hallucination).
- **One Agent = One File**: Mỗi agent là một file `.py` độc lập, tự chứa logic, metadata và policy riêng biệt.
- **Evidence-First**: Câu trả lời của Agent luôn phải dựa trên `row_id` hoặc `chunk_id` cụ thể trong Database.

---

## 2. Kiến trúc Hệ thống

### 2.1. Cấu trúc Thư mục (Repository Map)

```text
/apps
  /backend
    /src/app/agents/          # Nơi chứa code của từng Agent (Citizen, Legal, v.v.)
    /src/app/api/routes/      # FastAPI Routes (chat.py - Read Path)
    /src/app/core/            # Core Modules (RAG Pipeline, Database, Security)
    /src/test_agent_certification.py  # Test Suite bắt buộc (Certification)
  /ingestion
    /src/app/preproc/pipeline # Write Path (Orchestrator, Extract, Embed)
  /frontend                   # Next.js UI
/scripts                      # DevOps & Local Dev Scripts
/docs                         # Tài liệu dự án
```

### 2.2. Luồng dữ liệu (Data Flow)

#### Write Path (Ingestion)
Dữ liệu đi từ File nguồn -> Ingestion API -> Postgres & Qdrant.
- **Entrypoint**: `apps/ingestion/src/app/preproc/pipeline/orchestrator.py`
- **Quy trình**:
  1. **Extract**: Dùng ToolRegistry để chọn extractor phù hợp (PDF, Docx, v.v.).
  2. **Classify**: Phân loại tài liệu (Văn bản luật, Bảng biểu, Thông báo).
  3. **Parse**: Chia nhỏ thành `CanonicalChunk` (text) hoặc `CanonicalStructuredRow` (data).
  4. **Direct Write**: Ghi siêu dữ liệu vào Postgres (`documents`, `chunks`, `structured_rows`).
  5. **Background Sync**: Embed text và đẩy vector vào Qdrant (`gov_knowledge`).

#### Read Path (RAG & Agent)
Request đi từ User -> Backend API -> Agent -> RAG -> Response.
- **Entrypoint**: `apps/backend/src/app/api/routes/chat.py`
- **Quy trình**:
  1. **Router**: Xác định `agent_id` từ request hoặc Router Agent.
  2. **Registry Lookup**: `apps/backend/src/app/agents/registry.py` tìm instance Agent.
  3. **Agent Process**: Agent gọi `rag_retrieve` (trong `apps/backend/src/app/core/rag/pipeline.py`) với bộ lọc `doc_types` nghiêm ngặt.
  4. **Evidence Check**: Kiểm tra xem RAG có trả về context không. Nếu rỗng -> **Refusal**.
  5. **Generation**: LLM sinh câu trả lời dựa trên context đã tìm thấy.

---

## 3. Bảng chứng cứ (Evidence Table)

Hệ thống sử dụng mô hình Hybrid (Vector + Structured) lưu trên Postgres.

### Table: `structured_rows`
Dùng cho dữ liệu có cấu trúc (Danh sách hộ nghèo, Lịch công tác, Tra cứu nhân sự).

| Column | Type | Description |
| :--- | :--- | :--- |
| `row_id` | `TEXT (PK)` | ID duy nhất của dòng dữ liệu. |
| `doc_category` | `TEXT` | Phân loại (vd: `people`, `schedule`, `poverty_household`). |
| `commune_id` | `TEXT` | Scope dữ liệu (Tenant Isolation). |
| `data_content` | `JSONB` | Dữ liệu chính (vd: `{"full_name": "Nguyen Van A", "code": "A001"}`). |
| `citation` | `JSONB` | Nguồn gốc (File source, Sheet name, Row index). |
| `search_text` | `TEXT` | Trường text tổng hợp dùng cho Full-Text Search (FTS). |

### Table: `chunks` & `documents`
Dùng cho dữ liệu phi cấu trúc (Văn bản luật, Hướng dẫn).
- `chunks`: Chứa `display_text`, `embed_text` và `vector_id` (mapping sang Qdrant).

---

## 4. Danh mục Agent (Agent Catalog)

Tất cả Agent nằm trong `apps/backend/src/app/agents/`. Đăng ký tại `registry.py`.

| Agent ID | Tên File | Vai trò | Doc Types (Quyền đọc) |
| :--- | :--- | :--- | :--- |
| `citizen_agent` | `citizen_agent.py` | Hỏi đáp thủ tục hành chính, pháp luật chung. | `law`, `admin_procedure`, `citizen_guide` |
| `legal_agent` | `legal.py` | Tra cứu chuyên sâu văn bản luật. | `legal` |
| `people_lookup` | `people_lookup.py` | Tra cứu thông tin nhân sự (Demo). | `vectors` (metadata people) |
| `accurate_people`| `accurate_people.py`| Tra cứu nhân sự chính xác (SQL/Exact Match). | `structured_rows` (people) |
| `universal_lookup`| `universal_lookup.py`| Tra cứu đa năng (Hộ nghèo, Đất đai) dùng LLM Extract + SQL. | `people`, `poverty_household`, `land`, `schedule` |
| ... | ... | (Các agent Wave 2 khác: Economy, Meeting...) | ... |

---

## 5. Quy trình vận hành (Runbook)

### 5.1. Cài đặt môi trường (Local Dev)

**Yêu cầu**: Docker, Python 3.10+, Node.js 18+.

1.  **Clone Repo & Setup Env**:
    ```bash
    git clone <repo-url>
    cd gov-ai
    cp .env.example .env
    # Chỉnh sửa .env nếu cần (DB_URL, QDRANT_URL, API Keys)
    ```

2.  **Khởi động Infrastructure (Lite)**:
    ```bash
    docker compose -f docker-compose.local.yml up -d
    # Services: Backend(:8001), Ingestion(:8010), Qdrant(:6333), Postgres(:5432), FE(:3000)
    ```
    *Lưu ý: Script `run_local.sh` đã được patch để tránh conflict port 8000.*

3.  **Seed Dữ liệu mẫu (QA)**:
    ```bash
    # Reset DB và nạp dữ liệu test
    python3 scripts/dev_fast_setup.py --reset --embed mock
    ```

### 5.2. Chạy thử nghiệm (Testing)

Chúng tôi áp dụng chiến lược test đa tầng:

1.  **Certification Test (Bắt buộc trước PR)**:
    Kiểm tra tính tuân thủ contract, zero-trust imports và logic refusal.
    ```bash
    pytest apps/backend/src/test_agent_certification.py
    ```

2.  **Mocked Integration**:
    Test logic Agent mà không cần gọi LLM/DB thật.
    ```bash
    pytest apps/backend/tests/integration/test_agent_flow_mock.py
    ```

3.  **True E2E (Full Flow)**:
    Test toàn trình (Ingest -> RAG -> Chat). *Lưu ý: Cần API Key thật.*
    ```bash
    ./scripts/run_e2e_true.sh
    ```

### 5.3. Checklist Ngày đầu tiên (Day-1 Checklist)

- [ ] Đọc kỹ file `docs/DEV_AGENT_GUIDE.md` (Developer Agent Guide).
- [ ] Chạy thành công `scripts/dev_fast_setup.py`.
- [ ] Chạy pass `test_agent_certification.py`.
- [ ] Mở trình duyệt `http://localhost:3000` và chat thử với `citizen_agent`.
- [ ] Thử hỏi một câu không có trong dữ liệu và verify agent trả lời "Không tìm thấy thông tin" (Refusal).

---

## 6. Quản lý Rủi ro (Risks & Zero Check)

### Những điều TUYỆT ĐỐI CẤM (Zero-Trust Rules):

1.  **Không dùng Raw Client**:
    - ❌ `import requests`, `import psycopg2`, `import qdrant_client` trực tiếp trong file Agent.
    - ✅ Dùng Wrapper: `rag_retrieve`, `sql_execute_safe`, `web_search`.

2.  **Không Bypass Security Layer**:
    - Mọi query DB bắt buộc phải có `tenant_id` và `security_level`.
    - Không được tự ý query bảng `users` hoặc các bảng hệ thống.

3.  **Fail-Closed là bắt buộc**:
    - Nếu RAG trả về rỗng -> Phải return Refusal Code `NO_EVIDENCE`.
    - Không được để LLM tự "chém gió" khi thiếu context.

### Xử lý sự cố thường gặp
- **Lỗi `QDRANT_READONLY_API_KEY`**: Backend crash khi start. -> Kiểm tra `.env` hoặc `run_local.sh`, đảm bảo biến này được set (có thể dùng chung value với `QDRANT_API_KEY` ở local).
- **Lỗi Import**: Agent không chạy được. -> Kiểm tra `PYTHONPATH`. Chạy script từ root folder.
- **Port Conflict**: Không start được server. -> Check `lsof -i :8001` hoặc `8000`. Dùng `run_local.sh` để xử lý tự động.

---
*Tài liệu được cập nhật tự động bởi AI Assistant. Phiên bản: 1.0*
