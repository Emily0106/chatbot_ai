
from prometheus_client import Counter, Histogram

# Metric Definitions (Singleton)

INGEST_JOBS_TOTAL = Counter(
    "ingest_jobs_total", 
    "Total number of ingestion jobs submitted",
    ["status", "doc_type", "scope"]
)

INGEST_FILES_SIZE_BYTES = Histogram(
    "ingest_files_size_bytes",
    "Size of ingested files in bytes",
    ["mime_type"],
    buckets=[1024*100, 1024*1024, 10*1024*1024, 50*1024*1024] # 100KB, 1MB, 10MB, 50MB
)

INGEST_QUARANTINE_TOTAL = Counter(
    "ingest_quarantine_total",
    "Total items moved to quarantine",
    ["reason"]
)
