# HƯỚNG DẪN SỬ DỤNG HỆ THỐNG GOV-AI COCKPIT (Dành cho Quản trị viên Nghiệp vụ)

## 1. Giới thiệu
Tài liệu này hướng dẫn các thao tác quản trị trên **Cổng Quản trị AI (Admin Dashboard)**. Hệ thống giúp quản lý nguồn dữ liệu, duyệt các tài liệu mật, và giám sát quy trình xử lý dữ liệu tự động.

---

## 2. Quản lý Nguồn Dữ liệu (Sources)
Chức năng này dùng để kết nối một thư mục trên máy chủ (File Server) vào hệ thống AI mà không cần upload thủ công.

### Cách thêm một Nguồn mới:
1.  Truy cập tab **"🔌 Nguồn Dữ Liệu"**.
2.  Nhấn nút **"Thêm Nguồn Mới"**.
3.  Điền thông tin và **Gán Profile** (Xem mục 5 để chọn đúng).
4.  Nhấn **"Lưu Cấu Hình"**. Hệ thống sẽ tự động đồng bộ sau khoảng 30s.

> **Lưu ý kỹ thuật:** Folder Watcher phải đang chạy trên file server; file chỉ được ingest khi đã ổn định (không còn thay đổi/ghi đè).

---

## 3. Duyệt Tài liệu (Approval)
Để đảm bảo an toàn thông tin, tài liệu nhạy cảm (Profile Internal/Restricted) sẽ nằm ở trạng thái **"Chờ Duyệt"** (Quarantine) trước khi được AI học.

### Quy trình duyệt:
1.  Truy cập tab **"📋 Quản lý Job"**.
2.  Lọc trạng thái **"pending_approval"** (Chờ duyệt).
3.  Tại danh sách hiển thị, nhấn nút **"✅ Phê duyệt (Approve)"** ngay trên dòng tương ứng.
    *   *(Chỉ dùng ô nhập Job ID bên dưới khi cần xử lý nhanh theo mã mà không muốn tìm trong list)*.
4.  Sau khi duyệt, tài liệu sẽ chuyển sang trạng thái `queued` để xử lý.
    *   **Lưu ý:** Người dùng **đủ quyền** (đúng Tenant/Role) sẽ tra cứu được tài liệu này sau đóng Job hoàn tất (`done`).

---

## 4. Xử lý Lỗi & Giám sát (Troubleshooting)

### Trạng thái Job là gì?
*   `queued`: Đã vào hàng đợi xử lý.
*   `processing`: Đang thực hiện OCR, bóc tách dữ liệu.
*   `done`: Hoàn tất, dữ liệu đã sẵn sàng để hỏi đáp.
*   `failed`: Gặp lỗi (file hỏng, timeout...).
*   `pending_approval`: Đang chờ Admin duyệt.

### Cách xử lý lỗi:
1.  Lọc trạng thái **"failed"**.
2.  Xem chi tiết lỗi (ví dụ: `File corrupted`).
3.  Nhấn nút **"🔄 Thử lại (Retry Job)"** để hệ thống xử lý lại.

### Tra cứu Nhật ký (Audit):
*   Truy cập tab **"📝 Nhật ký"** để xem lịch sử ai đã Duyệt/Retry/Xóa.

---

## 5. Hướng dẫn Nhập liệu & Gán Metadata
Hệ thống sử dụng **"Profile"** (Mẫu hồ sơ) để tự động gán metadata chuẩn. **Lưu ý: Profile đã chọn thì metadata không chỉnh tay (Scope, Security, DocType).**

### Bảng chọn Profile (Khuyên dùng)

| Tên Profile (Option) | Metadata Tự động | Mục đích sử dụng | Thời gian hiệu lực |
| :--- | :--- | :--- | :--- |
| **Public (Công khai)** | Scope=**Public**<br>Security=Level 1 | Văn bản nội quy, thông báo chung. | **Ngay lập tức** (Auto-Approve) |
| **Internal (Nội bộ)** | Scope=**Internal**<br>Security=Level 3 | Biên bản họp, tài liệu dự án. | **Chờ duyệt** (Cần Admin Approve) |
| **Restricted (Mật)** | Scope=**Restricted**<br>Security=Level 4/5 | Hồ sơ nhân sự, chiến lược, bí mật nhà nước. | **Chờ duyệt** (Quy trình nghiêm ngặt) |

### Câu hỏi thường gặp
1.  **Tôi muốn dùng ngay lập tức?** -> Chọn Profile **Public**.
2.  **Tôi muốn upload vào DB để lưu trữ nhưng chưa dùng?** -> Chọn Profile **Internal/Restricted**. File sẽ nằm trong kho chờ duyệt (`pending_approval`).

---

## 6. Phân quyền (RBAC) - Ai được làm gì?

| Chức năng | Admin / Officer | Citizen (Người dân) |
| :--- | :---: | :---: |
| Truy cập Dashboard Admin | ✅ | ⛔ (403 Forbidden) |
| Tạo Nguồn dữ liệu | ✅ | ⛔ |
| Duyệt bài (Approve) | ✅ | ⛔ |
| Xem Audit Log | ✅ | ⛔ |
| Hỏi đáp Chatbot | ✅ | ✅ (Chỉ dữ liệu Public) |

---
**Hỗ trợ kỹ thuật:** Liên hệ Đội Vận hành Hạ tầng (Ops Team) khi gặp lỗi hệ thống.
