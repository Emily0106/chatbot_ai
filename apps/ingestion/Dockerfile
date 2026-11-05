FROM python:3.11-slim

WORKDIR /app

# deps hệ thống cho OCR/PDF và build extensions (tree-sitter, etc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils tesseract-ocr \
    build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Pre-install torch CPU to avoid huge download timeouts
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

COPY apps/ingestion/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY libs/core_shared /app/libs/core_shared
RUN pip install -e /app/libs/core_shared

COPY apps/ingestion/src /app/src
ENV PYTHONPATH=/app/src:/app

EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
