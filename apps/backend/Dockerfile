FROM python:3.11-slim

WORKDIR /app

COPY apps/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt


# shared lib
COPY libs/core_shared /app/libs/core_shared
RUN pip install -e /app/libs/core_shared

# Prefetch models
ENV HF_HOME=/app/models_cache
RUN pip install sentence-transformers
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"

# app code
COPY apps/backend/src /app/src
ENV PYTHONPATH=/app/src

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
