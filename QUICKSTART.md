# QUICKSTART: AI Gov Platform (10 Phút)

Hướng dẫn chạy hệ thống chatbot RAG từ đầu đến khi có thể chat.

---

## ⚡ TL;DR (3 Lệnh)

```bash
make up                    # Start tất cả services
make ingest-demo           # Upload dữ liệu demo (optional)
curl http://localhost:8000/health/ready  # Verify
```

---

## 📋 Prerequisites

Cài đặt trước:
- **Docker Desktop** (hoặc Docker Engine + Docker Compose)
- **Git**
- **8GB RAM** minimum
- **GPU** (optional, cho reranking nhanh hơn)

Kiểm tra version:
```bash
docker --version          # >= 20.10
docker compose version    # >= 2.0
git --version             # >= 2.x
```

---

## 🚀 Bước 1: Clone & Setup (2 phút)

```bash
# Clone repo
git clone https://github.com/<your-username>/chatbot_ai.git
cd chatbot_ai

# (Optional) Copy environment file
# Nếu không copy, `make up` sẽ tự động tạo từ .env.example
cp env/.env.example env/dev.env
```

---

## ⚙️ Bước 2: Configure (Optional, 2 phút)

Mở `env/dev.env` và chỉnh sửa (nếu cần):

### **2.1 OpenAI API Key** (Bắt buộc nếu dùng OpenAI)

```bash
# Thêm key của bạn
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxx

# Model name (default: gpt-4o-mini, rẻ nhất)
OPENAI_MODEL_NAME=gpt-4o-mini

# Embedding model
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

### **2.2 Reranking (Quan trọng cho accuracy)**

```bash
# ⚠️ BẬT RERANK CHO GOV MODE (high accuracy)
RERANK_ENABLED=true

# Retrieval mode: eco (fast) | gov (accurate) | auto (adaptive)
RETRIEVAL_MODE=auto
```

### **2.3 Database (Có thể giữ nguyên)**

```bash
POSTGRES_USER=app
POSTGRES_PASSWORD=dev_password_change_in_prod
POSTGRES_DB=rag_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
```

---

## 🐳 Bước 3: Start Services (3 phút)

```bash
# ONE COMMAND để dựng tất cả
make up
```

**Output mong đợi**:
```
[+] Building 15.2s (backend)
[+] Building 12.5s (ingest-api)
[+] Building 11.8s (ingest-worker)
[+] Running 7/7
 ✔ Container postgres-1         Healthy
 ✔ Container redis-1            Started
 ✔ Container qdrant-1           Started
 ✔ Container backend-1          Started
 ✔ Container ingest-api-1       Started
 ✔ Container ingest-worker-1    Started
 ✔ Container frontend-1         Started
```

**Services đang chạy**:
| Service | Port | Description |
|---------|------|-------------|
| `backend` | 8000 | RAG chatbot API |
| `ingest-api` | 8010 | Upload & job management |
| `ingest-worker` | - | Celery worker (background) |
| `postgres` | 5432 | Database (metadata) |
| `qdrant` | 6333 | Vector database |
| `redis` | 6379 | Queue & cache |
| `frontend` | 5173 | Web UI (stub) |

---

## ✅ Bước 4: Verify Health (30 giây)

```bash
# 1. Check containers running
make ps
# Kết quả: Tất cả services status = "Up"

# 2. Check logs (optional)
make logs
# Ctrl+C để thoát

# 3. Health check
curl http://localhost:8000/health
# → {"status":"ok"}

# 4. Readiness check (database, vector_db, cache)
curl http://localhost:8000/health/ready
# → {"database":"ok","vector_db":"ok","cache":"ok"}
```

**⚠️ Nếu lỗi**: Xem [Troubleshooting](#troubleshooting) phía dưới.

---

## 📄 Bước 5: Upload Document (2 phút)

### **Option A: Upload file của bạn**

```bash
curl -X POST http://localhost:8010/api/v1/ingest \
  -F "file=@/path/to/your/document.pdf" \
  -F "scope=local_gov" \
  -F "commune_id=xa_demo" \
  -F "doc_category_hint=procedure"
```

**Response**:
```json
{
  "status": "accepted",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "checksum": "abc123def456...",
  "filename": "document.pdf",
  "message": "Job queued."
}
```

### **Option B: Upload demo data (people_demo)**

```bash
make ingest-demo
# → Uploads sample "people" data for testing
```

---

## 🔍 Bước 6: Check Job Status (30 giây)

```bash
# Sao chép job_id từ bước 5
JOB_ID="550e8400-e29b-41d4-a716-446655440000"

# Poll status
curl http://localhost:8010/api/v1/jobs/$JOB_ID | jq .
```

**Response (processing)**:
```json
{
  "job_id": "550e8400-...",
  "status": "running",
  "progress": 45,
  "created_at": "2026-01-13T10:00:00Z"
}
```

**Response (done)**:
```json
{
  "job_id": "550e8400-...",
  "status": "done",
  "progress": 100,
  "doc_id": "doc_uuid_abc123",
  "finished_at": "2026-01-13T10:01:23Z"
}
```

**Auto-poll script**:
```bash
while true; do
  STATUS=$(curl -s http://localhost:8010/api/v1/jobs/$JOB_ID | jq -r '.status')
  echo "[$(date +%H:%M:%S)] Job status: $STATUS"
  [[ "$STATUS" == "done" ]] && break
  [[ "$STATUS" == "failed" ]] && echo "Job failed!" && break
  sleep 3
done
```

---

## 💬 Bước 7: Chat with RAG (1 phút)

### **Non-streaming request**

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "thủ tục đăng ký hộ tịch là gì?",
    "agent_id": "universal",
    "tenant_id": "xa_demo",
    "stream": false
  }' | jq .
```

**Response**:
```json
{
  "answer": "Thủ tục đăng ký hộ tịch bao gồm các bước sau:\n1. Chuẩn bị hồ sơ...\n2. Nộp hồ sơ tại UBND xã...",
  "citations": [
    {
      "chunk_id": "chunk_uuid_123",
      "title": "Luật Hộ tịch 2014",
      "source_url": "file:///storage/...",
      "page_number": 5,
      "score": 0.87,
      "snippet": "Điều 7. Thủ tục đăng ký khai sinh gồm..."
    }
  ],
  "meta": {
    "latency_ms": 850,
    "cache_hit": false,
    "citations_count": 3,
    "agent_id": "universal"
  }
}
```

### **Streaming request** (SSE)

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "hướng dẫn làm giấy khai sinh",
    "agent_id": "universal",
    "stream": true
  }'
```

**Response** (Server-Sent Events):
```
data: {"type":"chunk","content":"Hướng"}
data: {"type":"chunk","content":" dẫn"}
data: {"type":"chunk","content":" làm"}
...
data: {"type":"citations","citations":[...]}
data: {"type":"done","meta":{...}}
```

---

## 🧪 Bước 8: Verify Data (Optional)

### **Check Postgres**

```bash
# List documents
docker compose -f infra/compose/docker-compose.yml exec postgres \
  psql -U app -d rag_db \
  -c "SELECT doc_id, title, doc_category FROM documents LIMIT 5;"
```

### **Check Qdrant**

```bash
# Scroll vector points
curl -X POST "http://localhost:6333/collections/gov_knowledge/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{
    "limit": 3,
    "with_payload": true,
    "with_vector": false
  }' | jq '.result.points[].payload | {chunk_id, title, chunk_text}'
```

### **Check Ingestion Jobs**

```bash
# List all jobs
docker compose -f infra/compose/docker-compose.yml exec postgres \
  psql -U app -d rag_db \
  -c "SELECT job_id, status, progress, created_at FROM ingestion_jobs ORDER BY created_at DESC LIMIT 10;"
```

---

## 🎉 Success! Bạn đã sẵn sàng

Hệ thống đã chạy end-to-end:
- ✅ Upload documents → processed by worker
- ✅ Metadata in Postgres, vectors in Qdrant
- ✅ Chat query → retrieval → citations

---

## 🔧 Common Commands

```bash
# Stop all services
make down

# Restart services
make restart

# View logs (real-time)
make logs

# Reset demo data (delete Qdrant collection + Postgres rows)
make reset-demo

# Rebuild images (after code change)
make down && make up
```

---

## 🐛 Troubleshooting

### **Problem 1: "Connection refused" khi curl**

**Cause**: Services chưa ready

**Fix**:
```bash
# Wait 30s cho services boot
sleep 30

# Hoặc check logs
make logs | grep "Application startup complete"
```

---

### **Problem 2: Worker không consume jobs (status stuck "queued")**

**Cause**: Celery worker chưa start hoặc Redis connection failed

**Fix**:
```bash
# Check worker logs
docker logs ingest-worker-1

# Expected output:
# [INFO] celery@worker ready.
# [INFO] connected to redis://redis:6379/0

# If error: restart worker
docker restart ingest-worker-1
```

---

### **Problem 3: Postgres healthcheck failed**

**Cause**: Database chưa init xong

**Fix**:
```bash
# Check postgres logs
docker logs postgres-1

# Wait for "database system is ready to accept connections"

# Manual healthcheck
docker exec -it postgres-1 pg_isready -U app -d rag_db
```

---

### **Problem 4: Chat returns "Không đủ thông tin trong kho"**

**Possible causes**:
1. **No data uploaded**: Check `SELECT count(*) FROM documents;` > 0
2. **Wrong tenant_id**: Pass correct `tenant_id` in chat request
3. **Gate too strict**: Enable rerank in `env/dev.env`: `RERANK_ENABLED=true`
4. **Wrong doc_category**: Check agent uses correct filters

**Debug**:
```bash
# Check rag_trace logs
docker logs backend-1 | grep "rag_trace" | jq .

# Look for:
# - "attempts[0].hits" > 0 (retrieval found chunks)
# - "evidence_ok": false (gate rejected)
# - "evidence_info.reason" (why gate failed)
```

---

### **Problem 5: Slow ingestion (job stuck at 50%)**

**Cause**: Heavy PDF extraction (Docling OCR)

**Fix**:
```bash
# Option 1: Use fast lane for simple PDFs
# In upload:
curl ... -F "doc_category_hint=text_only"

# Option 2: Check worker has GPU access
docker logs ingest-worker-1 | grep "GPU"

# Option 3: Increase worker timeout (env/dev.env)
CELERY_TASK_TIME_LIMIT=600  # 10 minutes
```

---

## 📚 Next Steps

1. **Upload real data**: Batch upload với script [upload_xa_docs.sh](scripts/upload_xa_docs.sh)
2. **Tune retrieval**: Adjust thresholds trong `env/dev.env` (xem Core Readiness Report)
3. **Create custom agents**: Follow [Agent Development Guide](docs/agent_development.md)
4. **Production deploy**: Use `docker-compose.prod.yml` với secrets management

---

## 🆘 Need Help?

- 📖 [README.md](README.md) - Full documentation
- 🐛 [Core Readiness Report](docs/core_readiness_report.md) - Known issues & fixes

---

**Happy Chatting! 🤖**
