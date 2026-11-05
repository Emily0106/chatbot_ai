# TỔNG QUAN DỰ ÁN & PHÂN TÍCH KHOẢNG TRỐNG (PROJECT OVERVIEW & GAPS)

**Dự án**: Gov-AI Platform
**Phiên bản tài liệu**: 1.0
**Cập nhật lần cuối**: 2026-02-03
**Trạng thái**: Đang phát triển tích cực (Active Development)

---

## 1. Executive Summary

Gov-AI là nền tảng trợ lý ảo phục vụ Chính phủ điện tử, được thiết kế với tiêu chuẩn "Gov-Grade Reliability". Khác với các chatbot thông thường, hệ thống đặt sự an toàn và chính xác lên hàng đầu.

**Nguyên lý cốt lõi (Core Principles):**
1.  **Zero-Trust**: Không tin tưởng bất kỳ thành phần nào (Input người dùng, Output LLM, External API) nếu không qua kiểm duyệt.
2.  **Fail-Closed**: Thà không trả lời (từ chối dịch vụ) còn hơn trả lời sai. Nếu không tìm thấy chứng cứ (evidence) trong Database -> Trả về `NO_EVIDENCE`.
3.  **One Agent = One File**: Kiến trúc Agent độc lập, dễ kiểm toán và phân quyền.
4.  **Evidence-First**: Mọi câu trả lời phải được neo (grounding) vào trích dẫn cụ thể (Chunk/Row).

---

## 2. What We Have Built

Tính đến thời điểm hiện tại, nền tảng bao gồm các phân hệ chính:

*   **Ingestion Service (Write Path)**:
    *   Xử lý tài liệu đa định dạng (PDF, Docx, Excel).
    *   Phân loại tự động (Văn bản luật, Bảng biểu, Thông báo).
    *   Trích xuất dữ liệu có cấu trúc (Structured Rows) và phi cấu trúc (Chunks).
    *   Đồng bộ dữ liệu sang Vector Database (Qdrant) và Relational Database (Postgres).
*   **Backend Service (Read Path)**:
    *   Hệ thống Router thông minh phân tải request tới Agent phù hợp.
    *   **Agent Framework**: Quản lý 10+ agents chuyên biệt (Công dân, Pháp luật, Đất đai...).
    *   **RAG Pipeline**: Tìm kiếm lai (Hybrid Search) với cơ chế Evidence Gating nghiêm ngặt.
*   **Dev Tools**:
    *   **Lite Dev Kit**: Môi trường phát triển cục bộ tinh gọn (Docker Compose Lite).
    *   **Certification Suite**: Bộ test tự động đảm bảo chất lượng Agent trước khi merge.
    *   **Admin UI**: Giao diện quản trị (Cockpit) để theo dõi ingestion và log (đang hoàn thiện).

---

## 3. System Map

### 3.1. Write Path (Ingestion)
Dữ liệu được nạp vào hệ thống để tạo "Knowledge Base".
- **Entrypoint**: `apps/ingestion/src/app/preproc/pipeline/orchestrator.py`
- **Flow**:
  `Source File` -> `Orchestrator` -> `Extractor` -> `Classifier` -> `Parser` -> `Postgres (Golden Record)` -> `Embedder` -> `Qdrant (Vector Index)`

### 3.2. Read Path (Chat & Retrieval)
Người dùng hỏi và nhận câu trả lời.
- **Entrypoint**: `apps/backend/src/app/api/routes/chat.py`
- **Flow**:
  `User Req` -> `Router` -> `Agent Registry` (`apps/backend/src/app/agents/registry.py`) -> `Agent Instance` -> `RAG Pipeline` (`apps/backend/src/app/core/rag/pipeline.py`) -> `LLM` -> `User Res`

---

## 4. Current Status (Milestones Done)

Chúng ta đã hoàn thành các cột mốc nền tảng (Foundation):

*   **[DONE] PR-A1: Vector Parity Stabilization**: Chuẩn hóa kích thước vector **768** dimensions toàn hệ thống. Config Qdrant và Embedder đã đồng bộ.
*   **[DONE] PR-A2: Centralized Config**: Quy hoạch lại biến môi trường và config file, giảm thiểu lỗi drift giữa các môi trường (Dev/Prod).
*   **[DONE] PR-B0: Agent Contract & Registry**: Xây dựng khung làm việc cho Agent. Bắt buộc metadata, policy và fail-closed behavior.
*   **[DONE] Scaffolding (Wave 1 + Wave 2)**: Đã tạo khung cho **11 agents** mới (Meeting, Calendar, Land, Economy, Social, v.v.) cùng với các tool notes và policy cơ bản.

---

## 5. Gaps & Risks

Mặc dù nền tảng đã ổn định, vẫn còn các vấn đề tồn đọng cần giải quyết theo độ ưu tiên:

### P0 - Critical (Ảnh hưởng trực tiếp đến Production/Security)
1.  **Padding Hotfix (Technical Debt)**: Hệ thống đang dùng code "chữa cháy" để zero-pad vector từ 384 lên 768. Cần thay thế bằng model chuẩn 768 hoặc re-index lại toàn bộ dữ liệu.
    *   *Impact*: Giảm độ chính xác tìm kiếm vector.
2.  **Missing `apps/watcher`**: Component Watcher (giám sát thay đổi file/db) được nhắc đến trong kiến trúc nhưng **không tồn tại** trong source code hiện tại.
    *   *Impact*: Thiếu khả năng phản ứng thời gian thực với sự thay đổi dữ liệu.
3.  **True E2E Flakiness**: Test E2E thực tế (kết nối API thật) hay bị fail do timeout CPU (khi rerank) hoặc lỗi đóng event loop.
    *   *Impact*: Khó tự tin khi deploy production (CI/CD pipeline không xanh 100%).

### P1 - High (Ảnh hưởng đến tính năng/Trải nghiệm)
1.  **Agent Logic "Hollow"**: 11 agents mới chỉ có khung (scaffolding), chưa có logic nghiệp vụ sâu (vẫn dùng RAG chung chung). Cần implement tool riêng cho từng domain (VD: Land Agent cần query GIS, Calendar Agent cần gọi API lịch).
2.  **Frontend Parity**: Giao diện Admin/Chat chưa phản ánh hết các tính năng mới của Backend (Agent switching, streaming logs).

### P2 - Medium (Cải tiến/Clean-up)
1.  **Log Noise**: Log hệ thống còn nhiều tin rác, chưa chuẩn hóa format JSON để đẩy về ELK/Loki.
2.  **Doc Coverage**: Tài liệu API (Swagger/OpenAPI) chưa cập nhật tự động theo các thay đổi mới nhất của Agent.

---

## 6. Next Roadmap (Top 10 PRs)

Kế hoạch phát triển tiếp theo để đóng các Gap trên:

1.  **Refactor**: Remove Padding Hotfix & Re-index with proper 768 model.
2.  **Infra**: Implement `apps/watcher` service (File System Watcher -> Ingestion Trigger).
3.  **Test**: Fix E2E Flakiness (Tăng timeout, tách process rerank, mock heavy components trong CI).
4.  **Feat**: Implement `LandAgent` logic (GIS lookup stub).
5.  **Feat**: Implement `MeetingAgent` logic (Summarization flow).
6.  **Feat**: Implement `CalendarAgent` logic (Google/Outlook API connector stub).
7.  **UX**: Update Frontend để hiển thị Agent Status & Refusal Reason rõ ràng.
8.  **Ops**: Setup ELK Stack & Centralized Logging.
9.  **Sec**: Audit lại toàn bộ Role/Permission (Security Level enforcement).
10. **Doc**: Auto-generate SDK client cho các bên thứ 3 tích hợp.

---

## 7. How To Run Locally (Dev/Lite)

Dành cho developer muốn chạy nhanh hệ thống trên máy cá nhân.

### 7.1. Khởi động (Startup)
```bash
# 1. Clone & Setup Env
cp .env.example .env

# 2. Start Services (Backend, Ingestion, Qdrant, PG, FE)
# Lưu ý: Script đã fix lỗi xung đột port 8000
./run_local.sh

# 3. Chờ services healthy (khoảng 30s)
# Backend: http://localhost:8001/health
# Ingestion: http://localhost:8010/health
```

### 7.2. Seed Data (Tạo dữ liệu giả)
```bash
# Xóa sạch và nạp dữ liệu mẫu để test
python3 scripts/dev_fast_setup.py --reset --embed mock
```

---

## 8. Testing Strategy

*   **Khi nào chạy cái gì?**
    *   **Trước khi commit**: Chạy `test_agent_certification.py`. (Bắt buộc)
    *   **Khi sửa logic Agent**: Chạy `test_agent_flow_mock.py`.
    *   **Trước khi Release**: Chạy `./scripts/run_e2e_true.sh`. (Chấp nhận flaky, retry nếu fail do timeout).

*   **Lệnh chạy test certification**:
    ```bash
    pytest apps/backend/src/test_agent_certification.py
    ```

---

## 9. Known Issues & Mitigations

| Vấn đề | Nguyên nhân | Cách giảm thiểu (Workaround) |
| :--- | :--- | :--- |
| **Rerank Timeout** | CPU quá tải khi chạy Cross-Encoder Rerank. | Tắt Rerank ở local (`RERANK_ENABLED=False`) hoặc tăng request timeout. |
| **Event Loop Closed** | Lỗi trong `pytest-asyncio` khi dùng scope `module` cho event loop. | Dùng scope `function` hoặc chạy test đơn lẻ. |
| **Backend Crash Startup** | Thiếu biến môi trường `QDRANT_READONLY_API_KEY`. | Đảm bảo `.env` có key này (có thể đặt giống `QDRANT_API_KEY`). |
| **Vector DB Mismatch** | Dùng sai model embed (384 vs 768). | Luôn chạy `scripts/verify_parity.py` để kiểm tra cấu hình. |

---

## 10. Appendix

### 10.1. Agent Taxonomy (Scaffolded Agents)

Danh sách 11 Agents đã được scaffold (nằm trong `apps/backend/src/app/agents/`):

| Agent ID | File Name | Doc Types | Ghi chú |
| :--- | :--- | :--- | :--- |
| **citizen_agent** | `citizen_agent.py` | `law`, `admin_procedure`, `citizen_guide` | Hỏi đáp chung cho công dân. |
| **report_agent** | `report_agent.py` | `internal_report`, `stats` | Tổng hợp báo cáo. |
| **health_agent** | `health_agent.py` | `health_guidelines` | Y tế, sức khỏe. |
| **culture_agent** | `culture_agent.py` | `culture_guide`, `tourism_spots` | Văn hóa, du lịch. |
| **agri_agent** | `agri_agent.py` | `agri_tech` | Nông nghiệp. |
| **meeting_agent** | `meeting_agent.py` | `meeting_minutes` | Tra cứu biên bản họp. |
| **calendar_agent** | `calendar_agent.py` | `schedule_lookup` | Lịch công tác. |
| **economy_agent** | `economy_agent.py` | `stats`, `business_news` | Kinh tế, thị trường. |
| **doc_manager** | `doc_manager.py` | `official_document` | Quản lý văn bản đi/đến. |
| **land_agent** | `land_agent.py` | `land_planning`, `construction_permit` | Đất đai, xây dựng. |
| **social_agent** | `social_agent.py` | `social_policy` | Chính sách xã hội. |

### 10.2. Core/Legacy Agents (Ngoài danh sách trên)
*   `legal.py`: Tra cứu văn bản luật chuyên sâu.
*   `people_lookup.py` & `accurate_people.py`: Tra cứu nhân sự (Demo & SQL).
*   `universal_lookup.py`: Agent đa năng dùng LLM Extraction.

### 10.3. Doc Type Supported (Taxonomy)
`law`, `admin_procedure`, `citizen_guide`, `meeting_minutes`, `internal_report`, `stats`, `official_document`, `land_planning`, `construction_permit`, `social_policy`, `agri_tech`, `health_guidelines`, `culture_guide`, `tourism_spots`.
