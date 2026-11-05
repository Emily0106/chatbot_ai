# GOV-AI COCKPIT - HANDOVER PACK v1.0

**Date:** 2026-01-29
**Version:** v1.1.0 (Enterprise Pilot)
**Status:** READY FOR PILOT

---

## 1. Executive Summary
Hệ thống Gov-AI Cockpit đã hoàn tất giai đoạn phát triển Pilot (P0+P1+P2). Hệ thống hiện tại đáp ứng đầy đủ các tiêu chuẩn về **Bảo mật (Zero Trust)**, **Quản trị (Governance)** và **Vận hành (Ops Maturity)**.

**Khả năng chính:**
*   **Ingestion Thông minh**: Tự động hóa việc thu thập dữ liệu từ file server phân tán.
*   **Kiểm soát chặt chẽ**: Quy trình duyệt tin (Approve) và phân quyền (RBAC) cho tài liệu mật.
*   **Vận hành bền vững**: Có cơ chế tự khôi phục (Retry), giám sát (Metrics) và truy vết (Audit).

---

## 2. Ops Checklist (Bàn giao Vận hành)
Đội ngũ vận hành cần tiếp nhận các tài liệu và công cụ sau:

*   [x] **Source Code & Docker Images**: Tag `v1.1.0`.
*   [x] **Database Schema**: Đã bao gồm `registered_sources`, `audit_logs`.
*   [x] **Tài liệu Hướng dẫn**:
    *   `docs/USER_GUIDE.md`: Cho Admin nghiệp vụ.
    *   `docs/OPS_CHEATSHEET.md`: Cho SysAdmin.
*   [x] **Công cụ Admin Dashboard**: URL `http://<server-ip>:8501`.

## 3. Known Issues (Lưu ý)
*   **Watcher Heartbeat**: Số lượng "Active Watchers" dựa trên heartbeat 5 phút. Nếu server mất mạng, chỉ số này sẽ về 0 sau 5 phút.
*   **Large Files**: Upload qua UI giới hạn dung lượng do cấu hình Streamlit/Nginx. Khuyến nghị dùng Watcher cho file lớn >100MB.

## 4. Contacts
*   **Solution Architect**: [Name]
*   **Lead Developer**: Antigravity (AI Agent)
