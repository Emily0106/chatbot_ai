# Lệnh Chạy Nhanh - AI Gov Platform

Tài liệu tham khảo nhanh các lệnh thường dùng.

---

## 🚀 Setup & Start

```bash
# Clone repo
git clone https://github.com/<your-username>/chatbot_ai.git
cd chatbot_ai

# Start tất cả services (one command)
make up

# Check status
make ps

# View logs
make logs

# Stop all
make down
```

---

## 📦 Upload Documents

### Upload single file
```bash
curl -X POST http://localhost:8010/api/v1/ingest \
  -F "file=@document.pdf" \
  -F "scope=local_gov" \
  -F "commune_id=xa_demo" \
  -F "doc_category_hint=procedure"
```

### Upload batch (loop)
```bash
for file in data/xa_demo/*.pdf; do
  curl -X POST http://localhost:8010/api/v1/ingest \
    -F "file=@$file" \
    -F "scope=local_gov" \
    -F "commune_id=xa_abc"
  echo "✓ $file"
done
```

### Check job status
```bash
JOB_ID="your-job-uuid"
curl http://localhost:8010/api/v1/jobs/$JOB_ID | jq .
```

---

## 💬 Chat API

### Non-streaming
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "câu hỏi của bạn",
    "agent_id": "universal",
    "tenant_id": "xa_demo",
    "stream": false
  }' | jq .
```

### Streaming (SSE)
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "câu hỏi của bạn",
    "agent_id": "universal",
    "stream": true
  }'
```

---

## 🔍 Database Queries

### Postgres - List documents
```bash
docker compose -f infra/compose/docker-compose.yml exec postgres \
  psql -U app -d rag_db \
  -c "SELECT doc_id, title, doc_category, created_at FROM documents ORDER BY created_at DESC LIMIT 10;"
```

### Postgres - List chunks
```bash
docker compose -f infra/compose/docker-compose.yml exec postgres \
  psql -U app -d rag_db \
  -c "SELECT chunk_id, LEFT(display_text, 100) AS snippet FROM chunks LIMIT 5;"
```

### Postgres - Count by category
```bash
docker compose -f infra/compose/docker-compose.yml exec postgres \
  psql -U app -d rag_db \
  -c "SELECT doc_category, COUNT(*) FROM documents GROUP BY doc_category;"
```

### Qdrant - Scroll points
```bash
curl -X POST "http://localhost:6333/collections/gov_knowledge/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{
    "limit": 10,
    "with_payload": true,
    "with_vector": false
  }' | jq '.result.points[].payload | {chunk_id, title}'
```

### Qdrant - Filter by tenant
```bash
curl -X POST "http://localhost:6333/collections/gov_knowledge/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {"key": "tenant_id", "match": {"value": "xa_demo"}},
        {"key": "doc_category", "match": {"value": "procedure"}}
      ]
    },
    "limit": 5,
    "with_payload": true
  }' | jq .
```

---

## 🔧 Maintenance

### Reindex document
```bash
DOC_ID="your-doc-uuid"
curl -X POST http://localhost:8010/api/v1/docs/$DOC_ID/reindex
```

### Delete document
```bash
DOC_ID="your-doc-uuid"
curl -X DELETE http://localhost:8010/api/v1/docs/$DOC_ID
```

### Reset demo data
```bash
make reset-demo
```

### Restart services
```bash
make restart

# Or restart specific service
docker restart backend-1
docker restart ingest-worker-1
```

### Rebuild after code change
```bash
make down
make up
```

---

## 📊 Monitoring

### Health checks
```bash
# Liveness
curl http://localhost:8000/health

# Readiness
curl http://localhost:8000/health/ready
```

### View logs (specific service)
```bash
docker logs backend-1 -f           # Backend
docker logs ingest-worker-1 -f     # Worker
docker logs postgres-1 -f          # Database
docker logs qdrant-1 -f            # Vector DB
```

### Search logs for trace
```bash
# Find RAG trace logs
docker logs backend-1 | grep "rag_trace" | jq .

# Find errors
docker logs backend-1 | grep "ERROR"

# Find specific query
docker logs backend-1 | grep "thủ tục"
```

### Check disk usage
```bash
docker system df
docker volume ls
```

---

## 🐛 Debug Commands

### Shell into container
```bash
docker exec -it backend-1 bash
docker exec -it ingest-worker-1 bash
docker exec -it postgres-1 bash
```

### Test database connection
```bash
docker exec -it postgres-1 pg_isready -U app -d rag_db
```

### Test Redis connection
```bash
docker exec -it redis-1 redis-cli ping
# → PONG
```

### Test Qdrant API
```bash
curl http://localhost:6333/collections
```

### Check GPU availability (in worker)
```bash
docker exec -it ingest-worker-1 python -c "import torch; print(torch.cuda.is_available())"
```

---

## 🧹 Cleanup

### Remove all containers & volumes
```bash
make down
```

### Remove only volumes (keep images)
```bash
docker compose -f infra/compose/docker-compose.yml down -v
```

### Clean Docker system
```bash
docker system prune -a --volumes
# ⚠️ Warning: This removes ALL unused containers, networks, images, and volumes!
```

---

## ⚙️ Configuration

### Edit environment
```bash
nano env/dev.env

# Common vars:
# RERANK_ENABLED=true
# RETRIEVAL_MODE=gov
# OPENAI_API_KEY=sk-...
```

### Reload config (restart needed)
```bash
docker restart backend-1
docker restart ingest-worker-1
```

---

## 📚 References

- [README.md](README.md) - Full documentation
- [QUICKSTART.md](QUICKSTART.md) - 10-minute setup guide
- [Makefile](Makefile) - Available make commands
- [docker-compose.yml](infra/compose/docker-compose.yml) - Service definitions
