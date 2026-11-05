# DEV QUICKSTART (Lite Mode)

Hướng dẫn này giúp developers dựng môi trường **Lite Stack** (Postgres + Qdrant) và nạp dữ liệu giả lập (Seeding) để phát triển Agent trên máy cá nhân, không cần Ingestion Pipeline phức tạp.

## 1. Yêu cầu
- Docker & Docker Compose
- Python 3.10+
- (Khuyên dùng) `fastembed` để vector search chính xác hơn: `pip install fastembed`

## 2. Khởi động Lite Stack
Chỉ chạy Database và Vector DB (nhẹ, <1GB RAM):

```bash
docker compose -f infra/docker-compose.lite.yml up -d
```

## 3. Nạp dữ liệu giả lập (Seeding)
Chạy script setup. Script này sẽ:
- Chạy Database Migration (dùng chung logic với Prod).
- Tạo Qdrant Collection (`gov_knowledge`).
- Nạp dữ liệu từ `fixtures/synthetic_corpus`.

```bash
# Linux/Mac
export ENV_MODE=dev
export DATABASE_URL="postgresql://dev:dev@localhost:5432/rag_db"
# Nếu chạy từ host, trỏ Qdrant về localhost
export QDRANT_URL="http://localhost:6333"

# KHUYẾN NGHỊ: Dùng --embed=fastembed để khớp với Backend config
python3 scripts/dev_fast_setup.py --reset --embed=fastembed
```

> **Lưu ý:**
> *   `--embed=mock`: Dùng vector giả (nhanh, không cần model). Retrieval sẽ dựa vào lexical (keyword) nếu backend hỗ trợ, hoặc trả về ngẫu nhiên.
> *   `--embed=fastembed`: Dùng model BAAI/bge-small (tải về máy), retrieval chính xác.

## 4. Cấu hình Backend
Để đảm bảo Backend chạy đúng với dữ liệu vừa seed (tránh lỗi Dimension mismatch 1536 vs 384), hãy cấu hình biến môi trường:

```bash
cp apps/backend/.env.example apps/backend/.env
```

Nội dung `.env` đã được chuẩn hóa cho Local Dev (FastEmbed + Qdrant Local).

## 5. Chạy Backend & Smoke Test
Mở terminal khác để chạy Backend:
```bash
uvicorn apps.backend.main:app --reload
```

Chạy Smoke Test để kiểm tra Gate/Policy:
```bash
python3 scripts/dev_smoke.py
```

## 6. Dữ liệu Test (Fixtures)
*   **Public**: Luật Trồng Cây (Ai cũng xem được).
*   **Internal**: Biên bản họp (Cần role Officer/Admin).
*   **Restricted**: Hồ sơ UFO (Cần Security Level cao).
