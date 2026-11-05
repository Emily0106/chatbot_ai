# CHANGELOG

## [v1.1.0] - Enterprise Pilot Ready - 2026-01-29

Phiên bản này đánh dấu bước chuyển mình từ Prototype sang Pilot (Có khả năng vận hành thực tế).

### 🚀 Tính năng Mới (New Features)
*   **Registered Sources (Quản lý Nguồn Dữ liệu)**:
    *   Cho phép Admin cấu hình folder giám sát thông qua giao diện UI (Tab "Nguồn Dữ Liệu").
    *   Watcher v2 tự động đồng bộ cấu hình từ Server (Polling mechanism), loại bỏ việc sửa file YAML thủ công.
*   **Ops Maturity (Vận hành Nâng cao)**:
    *   **Job Recovery**: Thêm nút "Retry" cho các job bị lỗi (Failed).
    *   **Audit Logging**: Hệ thống ghi nhật ký các hành động nhạy cảm (Duyệt, Retry, Sửa Source).
    *   **System Metrics**: Hiển thị thống kê nhanh (Tỷ lệ lỗi, Active Watchers) trên Dashboard.

### 🛠 Cải tiến (Improvements)
*   **Admin Dashboard UI**:
    *   Cải thiện độ ổn định tab "Trạng thái Hệ thống" (Connectivity Check).
    *   Phân loại lỗi rõ ràng (CORS vs 404 vs 500).
    *   Thêm tab "Nhật ký" và "Quản lý Job" chuyên biệt.
*   **Backend**:
    *   Tối ưu hóa API endpoint cho Health Check.
    *   Thêm bảng `registered_sources` và `audit_logs` vào Database Schema.

### 🐛 Sửa lỗi (Bug Fixes)
*   Khắc phục lỗi "Offline" giả trên Dashboard do sai đường dẫn API Health.
*   Sửa lỗi logic phân quyền trong luồng duyệt tài liệu (RBAC Enforcement).

### ⚠️ Lưu ý Vận hành (Ops Notes)
*   Cần chạy migration database để tạo bảng mới (`registered_sources`, `audit_logs`).
*   Watcher v1 (YAML only) vẫn được hỗ trợ nhưng khuyến nghị nâng cấp lên Watcher v2.
