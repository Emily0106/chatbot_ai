# OPS CHEATSHEET - GOV-AI COCKPIT (Dành cho DevOps/SysAdmin)

## 1. Triển khai & Vận hành (Deployment)

### Khởi động hệ thống
```bash
cd /opt/gov-ai-cockpit
docker compose up -d
```

### Kiểm tra Logs
```bash
# Xem logs toàn bộ
docker compose logs -f --tail 100

# Xem logs Admin Dashboard
docker logs -f compose-admin-dashboard

# Xem logs Ingestion API (Backend xử lý)
docker logs -f compose-ingest-api-1
```

### Database Migration
Khi có thay đổi schema (như `registered_sources` hay `audit_logs`):
```bash
# Chạy thủ công (nếu cần)
docker exec -it compose-ingest-api-1 python3 scripts/migrate_db.py
# Hoặc truy cập DB trực tiếp
docker exec -it compose-postgres-1 psql -U app -d rag_db
```

---

## 2. Thiết lập Folder Watcher (Trên File Server)

Folder Watcher là script Python chạy background để đồng bộ file từ server về hệ thống AI.

### Cài đặt (Trên máy chủ đích)
1.  Copy folder `tools/` lên máy chủ.
2.  Cài đặt dependencies:
    ```bash
    pip3 install -r tools/requirements.txt
    ```
    *(Gồm: requests, pyyaml, watchdog)*

3.  Cấu hình `tools/watcher_config.yaml`:
    ```yaml
    api_url: "http://<IP_COCKPIT_SERVER>:8010/api/v1"
    server_id: "FILE_SRV_01"  # Phải khớp với cấu hình trên Admin Dashboard
    auth:
      tenant_id: "default"    # Tenant tương ứng
      user_role: "admin"
    polling_interval: 30      # Giây
    ```

4.  Chạy Service (Systemd hoặc screen):
    ```bash
    python3 tools/folder_watcher.py
    ```
    *Dấu hiệu thành công:* Log hiển thị `Synced X bindings from API`.

---

## 3. Monitoring & Health Check

### Dashboard "Trạng thái" (Tab Status)
*   **Backend API / Ingestion API**: Phải có dấu ✅ "Hoạt động".
    *   Nếu ❌: Kiểm tra Container đang chạy không (`docker ps`).
*   **Quick Stats**:
    *   **Jobs Hôm nay**: Số lượng job tạo mới.
    *   **Tỷ lệ Lỗi**: Nếu > 10%, cần điều tra log Ingestion.
    *   **Active Watchers**: Số lượng watcher có heartbeat trong 5 phút qua. Nếu = 0, kiểm tra kết nối mạng giữa Cockpit và File Server.

### Xử lý sự cố thường gặp (Troubleshooting)
*   **Lỗi "Test Connection" trên UI**:
    *   Nguyên nhân: CORS, sai URL, hoặc container down.
    *   Khắc phục: Vào file `docker-compose.yml`, kiểm tra biến môi trường `BACKEND_URL`, `INGESTION_URL`.
*   **Job bị kẹt ở "processing" quá lâu**:
    *   Nguyên nhân: Worker bị oom-killed (hết RAM) hoặc task quá nặng.
    *   Khắc phục: Restart worker container. Dùng chức năng **Requeue** (nếu đã kích hoạt P2) hoặc xóa job tạo lại.

---

**Liên hệ Khẩn cấp:**
*   Dev Team Lead: [Email/Phone]
*   Database Admin: [Email/Phone]
