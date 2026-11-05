# AI Gov Platform

**Gov-grade RAG (Retrieval-Augmented Generation) chatbot** cho hệ thống chính quyền số cấp địa phương.

[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)

---

## 🎯 Tính Năng Chính

- ✅ **Hybrid Retrieval**: Dense (vector) + Sparse (BM25) + RRF Fusion
- ✅ **Multi-tenant**: Hỗ trợ nhiều đơn vị hành chính (xã/huyện/tỉnh)
- ✅ **Evidence-first**: Citations bắt buộc, không hallucination
- ✅ **Smart Ingestion**: Auto-routing (fast/heavy PDF extraction), parent-child chunking
- ✅ **Reranking**: Cross-encoder với circuit breaker (Gov mode)
- ✅ **Multi-format**: PDF, DOCX, Excel, CSV, Images (OCR)
- ✅ **Agent Framework**: Extensible agents cho từng lĩnh vực (legal, IP, land, health...)

---

## 🏗️ Kiến Trúc

```
┌─────────────┐
│   User      │
└──────┬──────┘
       │
       ├──────────────┐
       │              │
       ▼              ▼
┌─────────────┐  ┌──────────────┐
│  Frontend   │  │   Backend    │  ← RAG Engine (port 8000)
│  (Nginx)    │  │   (FastAPI)  │
└─────────────┘  └──────┬───────┘
                        │
       ┌────────────────┼────────────────┐
       │                │                │
       ▼                ▼                ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ Ingestion   │  │  Postgres    │  │   Qdrant     │
│   API       │  │  (Metadata)  │  │  (Vectors)   │
│ (port 8010) │  └──────────────┘  └──────────────┘
└──────┬──────┘
       │
       ▼
┌─────────────┐  ┌──────────────┐
│ Celery      │←→│    Redis     │
│  Worker     │  │   (Queue)    │
└─────────────┘  └──────────────┘
```

---

## 🚀 Quickstart (5 Phút)

### **Prerequisites**

- Docker + Docker Compose
- GPU (optional, cho reranking/embedding nhanh hơn)
- 8GB RAM minimum

### **1. Clone & Setup**

```bash
git clone https://github.com/<your-username>/chatbot_ai.git
cd chatbot_ai

# Copy env file (hoặc tự động tạo khi chạy make up)
cp env/.env.example env/dev.env
```

### **2. Configure Environment** (Optional)

Chỉnh sửa `env/dev.env`:

```bash
# Database
POSTGRES_USER=app
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=rag_db

# OpenAI (hoặc local LLM)
OPENAI_API_KEY=sk-...
OPENAI_MODEL_NAME=gpt-4o-mini

# Reranking (Gov mode - high accuracy)
RERANK_ENABLED=true   # ⚠️ Set to true for production

# Retrieval mode
RETRIEVAL_MODE=auto   # auto | eco | gov
```

### **3. Start All Services**

```bash
make up
```

**Lệnh này sẽ**:
- Build Docker images (backend, ingestion, worker)
- Start Postgres, Qdrant, Redis
- Run migrations (init database schema)
- Start backend API (port 8000)
- Start ingestion API (port 8010)
- Start Celery worker (auto-consume job queue)

### **4. Verify Health**

```bash
# Check all services running
make ps

# Check logs
make logs

# Health check
curl http://localhost:8000/health
# → {"status":"ok"}

curl http://localhost:8000/health/ready
# → {"database":"ok","vector_db":"ok","cache":"ok"}
```

### **5. Upload Your First Document**

```bash
curl -X POST http://localhost:8010/api/v1/ingest \
  -F "file=@your_document.pdf" \
  -F "scope=local_gov" \
  -F "commune_id=xa_demo" \
  -F "doc_category_hint=procedure"
```

**Response**:
```json
{
  "status": "accepted",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "checksum": "abc123...",
  "filename": "your_document.pdf"
}
```

### **6. Check Job Status**

```bash
JOB_ID="550e8400-e29b-41d4-a716-446655440000"
curl http://localhost:8010/api/v1/jobs/$JOB_ID
```

**Response**:
```json
{
  "job_id": "550e8400-...",
  "status": "done",       // queued → running → done/failed
  "progress": 100,
  "doc_id": "doc_uuid_...",
  "created_at": "2026-01-13T10:00:00Z",
  "finished_at": "2026-01-13T10:01:23Z"
}
```

### **7. Chat with RAG**

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "thủ tục đăng ký hộ tịch là gì?",
    "agent_id": "universal",
    "tenant_id": "xa_demo",
    "stream": false
  }'
```

**Response**:
```json
{
  "answer": "Thủ tục đăng ký hộ tịch bao gồm...",
  "citations": [
    {
      "chunk_id": "chunk_123",
      "title": "Luật Hộ tịch 2014",
      "source_url": "file:///.../document.pdf",
      "page_number": 5,
      "score": 0.87,
      "snippet": "Điều 7. Thủ tục đăng ký khai sinh..."
    }
  ],
  "meta": {
    "latency_ms": 850,
    "cache_hit": false,
    "citations_count": 3
  }
}
```

---

## 📦 Project Structure

```
AI_chat/
├── apps/
│   ├── backend/              # RAG chatbot backend (FastAPI)
│   │   ├── src/app/
│   │   │   ├── agents/       # Agent implementations (legal, IP, citizen_qa...)
│   │   │   ├── core/
│   │   │   │   ├── rag/      # RAG pipeline (retrieve, rerank, context, pipeline)
│   │   │   │   ├── llm/      # LLM clients (OpenAI, embeddings, reranking)
│   │   │   │   └── db_*.py   # Database connectors (Postgres, Qdrant, Redis)
│   │   │   ├── api/routes/   # FastAPI routes
│   │   │   └── main.py       # FastAPI app entrypoint
│   │   └── Dockerfile
│   │
│   ├── ingestion/            # Document ingestion service
│   │   ├── src/app/
│   │   │   ├── preproc/      # Preprocessing pipeline
│   │   │   │   ├── extractors/   # PDF/DOCX/Excel/Image extractors
│   │   │   │   ├── parsers/      # Legal/Narrative/Table parsers
│   │   │   │   ├── normalizers/  # Text cleaning, Vietnamese normalization
│   │   │   │   └── pipeline/     # Orchestrator
│   │   │   ├── workers/      # Celery worker
│   │   │   └── api/          # Upload/Job API
│   │   └── Dockerfile
│   │
│   └── frontend/             # Web UI (stub)
│
├── libs/
│   └── core_shared/          # Shared models (CanonicalDocument, CanonicalChunk...)
│
├── infra/
│   ├── compose/              # Docker Compose files
│   │   ├── docker-compose.yml       # Base services
│   │   ├── docker-compose.dev.yml   # Dev overrides (volume mounts, reload)
│   │   └── docker-compose.prod.yml  # Prod overrides
│   └── postgres/init/        # SQL migrations
│
├── env/
│   └── .env.example          # Environment template
│
├── storage/                  # File storage (mounted to containers)
│   └── raw_files/
│
├── models/                   # Local LLM models (optional)
├── tests/                    # Integration tests
├── Makefile                  # Convenience commands
└── README.md
```

---

## 🛠️ Makefile Commands

| Command | Description |
|---------|-------------|
| `make up` | Start all services (build + up -d) |
| `make down` | Stop and remove all containers + volumes |
| `make logs` | Tail logs from all services |
| `make ps` | List running containers |
| `make restart` | Restart all services |
| `make reset-demo` | Delete demo data (Qdrant collection + Postgres rows) |
| `make ingest-demo` | Run demo ingestion script |
| `make verify-demo` | Verify Qdrant data (scroll 3 points) |

---

## 🔧 Advanced Usage

### **Upload Bulk Documents**

```bash
# Upload all PDFs in a folder
for file in data/xa_demo/*.pdf; do
  curl -X POST http://localhost:8010/api/v1/ingest \
    -F "file=@$file" \
    -F "scope=local_gov" \
    -F "commune_id=xa_abc" \
    -F "doc_category_hint=procedure"
  echo "Uploaded: $file"
done
```

### **Reindex Existing Document**

```bash
DOC_ID="your_doc_uuid"
curl -X POST http://localhost:8010/api/v1/docs/$DOC_ID/reindex
```

### **Delete Document**

```bash
DOC_ID="your_doc_uuid"
curl -X DELETE http://localhost:8010/api/v1/docs/$DOC_ID
# → Returns job_id (async deletion: Postgres CASCADE + Qdrant points)
```

### **Query Postgres Directly**

```bash
# List documents
docker compose -f infra/compose/docker-compose.yml exec postgres \
  psql -U app -d rag_db \
  -c "SELECT doc_id, title, doc_category FROM documents LIMIT 10;"

# List chunks
docker compose -f infra/compose/docker-compose.yml exec postgres \
  psql -U app -d rag_db \
  -c "SELECT chunk_id, display_text FROM chunks WHERE doc_category='procedure' LIMIT 5;"
```

### **Query Qdrant Directly**

```bash
# Scroll points
curl -X POST "http://localhost:6333/collections/gov_knowledge/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{
    "limit": 10,
    "with_payload": true,
    "with_vector": false,
    "filter": {
      "must": [
        {"key": "tenant_id", "match": {"value": "xa_demo"}},
        {"key": "doc_category", "match": {"value": "procedure"}}
      ]
    }
  }' | jq .
```

### **Debug RAG Pipeline**

```bash
# Check trace logs
docker logs backend-1 | grep "rag_trace" | jq .

# Example trace:
# {
#   "trace_id": "abc123",
#   "ok": true,
#   "latency_ms": 850,
#   "cache_hit": false,
#   "citations_count": 3,
#   "attempts": [
#     {
#       "attempt": 0,
#       "hits": 30,
#       "retrieve_ms": 120,
#       "rerank_ms": 350,
#       "context_ms": 50,
#       "evidence_ok": true,
#       "evidence_info": {"reason": "fallback_rerank_logit_gate", "score": 2.5},
#       "used_tools": ["qdrant_hybrid"]
#     }
#   ]
# }
```

---

## 🧪 Testing

### **Run Unit Tests**

```bash
pytest tests/
```

### **Integration Test: End-to-End**

```bash
# 1. Upload document
JOB_ID=$(curl -s -X POST http://localhost:8010/api/v1/ingest \
  -F "file=@test_upload.txt" \
  -F "scope=local_gov" \
  | jq -r '.job_id')

# 2. Wait for job to finish
while true; do
  STATUS=$(curl -s http://localhost:8010/api/v1/jobs/$JOB_ID | jq -r '.status')
  echo "Job status: $STATUS"
  [[ "$STATUS" == "done" ]] && break
  sleep 2
done

# 3. Query chatbot
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test query","agent_id":"universal","stream":false}' \
  | jq .
```

---

## 🐛 Troubleshooting

### **Problem: Worker không consume jobs**

```bash
# Check worker logs
docker logs ingest-worker-1

# Common issues:
# - Redis not ready → wait for service_started
# - Celery broker connection failed → check REDIS_URL in env/dev.env
# - Python import errors → rebuild image: make down && make up
```

### **Problem: "No information" response**

**Possible causes** (theo Core Readiness Report):
1. **Data missing**: Check if documents exist
   ```bash
   psql -U app -d rag_db -c "SELECT count(*) FROM documents;"
   ```
2. **Gate too strict**: Enable rerank or lower thresholds
   ```bash
   # In env/dev.env:
   RERANK_ENABLED=true
   ```
3. **Wrong filters**: Check agent passes correct `doc_type`
   ```bash
   # In log: grep "rag_trace" | jq '.attempts[0].retrieve_debug.filters'
   ```

### **Problem: Slow retrieval (>2s)**

```bash
# Enable Eco mode (disable rerank)
# In env/dev.env:
RETRIEVAL_MODE=eco
RERANK_ENABLED=false

# Or optimize deadline
RETRIEVAL_DEADLINE_MS=1000  # from 1500ms → 1000ms
```

### **Problem: Postgres connection refused**

```bash
# Wait for healthcheck
docker logs postgres-1

# Manual check
docker exec -it postgres-1 pg_isready -U app -d rag_db
```

---

## 📚 Documentation

- 📖 [Core Readiness Report](docs/core_readiness_report.md) - System audit & optimization roadmap
- 🧭 [Architecture Guide](docs/architecture.md) - Deep dive vào RAG pipeline
- 🎓 [Agent Development](docs/agent_development.md) - Hướng dẫn tạo agent mới
- 🔍 [Troubleshooting Guide](docs/troubleshooting.md) - Debug common issues

---

## 🤝 Contributing

1. Fork repo
2. Tạo branch: `git checkout -b feature/my-feature`
3. Commit: `git commit -am 'Add my feature'`
4. Push: `git push origin feature/my-feature`
5. Tạo Merge Request

---

## 📝 License

All rights reserved (license to be decided).

---

## 👥 Authors

- **Backend**: AI Gov Platform Team
- **Ingestion**: Document Processing Team
- **Infrastructure**: DevOps Team

---

## 🙏 Acknowledgments

- FastAPI framework
- Qdrant vector database
- OpenAI API
- Docling (IBM) for document extraction
