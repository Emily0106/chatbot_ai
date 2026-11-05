# apps/backend/src/app/core/promotion/telemetry.py
import logging
import time
from typing import Optional, Dict, Any
from contextlib import contextmanager
import uuid

# Try to import prometheus_client, if not available, mock it or skip
try:
    from prometheus_client import Counter, Histogram
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False
    
logger = logging.getLogger(__name__)

# Metrics
if HAS_PROMETHEUS:
    PROMOTION_JOBS_TOTAL = Counter(
        "promotion_jobs_total", 
        "Total promotion jobs processed",
        ["status", "tenant_id"]
    )
    PROMOTION_JOB_DURATION_SECONDS = Histogram(
        "promotion_job_duration_seconds",
        "Time taken to process promotion job",
        ["status"]
    )
    PROMOTION_JOB_FAILURES_TOTAL = Counter(
        "promotion_job_failures_total",
        "Total promotion job failures",
        ["error_code"]
    )
    PROMOTION_JOBS_STUCK_TOTAL = Counter(
        "promotion_jobs_stuck_total",
        "Total promotion jobs recovered from stuck state"
    )
else:
    PROMOTION_JOBS_TOTAL = None
    PROMOTION_JOB_DURATION_SECONDS = None
    PROMOTION_JOB_FAILURES_TOTAL = None
    PROMOTION_JOBS_STUCK_TOTAL = None

class StructuredLogger:
    def __init__(self, job_id: str, tenant_id: str, trace_id: Optional[str] = None):
        self.context = {
            "job_id": str(job_id),
            "tenant_id": tenant_id,
            "trace_id": trace_id or str(uuid.uuid4())
        }
        
    def info(self, msg: str, **kwargs):
        logger.info(msg, extra={**self.context, **kwargs})
        
    def warning(self, msg: str, **kwargs):
        logger.warning(msg, extra={**self.context, **kwargs})
        
    def error(self, msg: str, **kwargs):
        logger.error(msg, extra={**self.context, **kwargs})

@contextmanager
def measure_duration(status_label: str = "unknown"):
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        if HAS_PROMETHEUS and PROMOTION_JOB_DURATION_SECONDS:
            PROMOTION_JOB_DURATION_SECONDS.labels(status=status_label).observe(duration)

def inc_job_counter(status: str, tenant_id: str):
    if HAS_PROMETHEUS and PROMOTION_JOBS_TOTAL:
        PROMOTION_JOBS_TOTAL.labels(status=status, tenant_id=tenant_id).inc()

def inc_failure_counter(error_code: str):
    if HAS_PROMETHEUS and PROMOTION_JOB_FAILURES_TOTAL:
        PROMOTION_JOB_FAILURES_TOTAL.labels(error_code=error_code).inc()

def inc_stuck_counter():
    if HAS_PROMETHEUS and PROMOTION_JOBS_STUCK_TOTAL:
        PROMOTION_JOBS_STUCK_TOTAL.inc()
