
# apps/backend/src/app/core/metrics.py
import time
from typing import Optional
from prometheus_client import Counter, Histogram, Gauge, REGISTRY, generate_latest, CONTENT_TYPE_LATEST

# ----------------------------------------------------------------------
# 1. Define Metrics (Singleton)
# Use prefix 'govai_' for namespace
# ----------------------------------------------------------------------

# Counter: Chat Requests
# Labels: agent_id, lane, stream (true/false), status (ok/refused/error/rate_limited/forbidden)
CHAT_REQUESTS_TOTAL = Counter(
    "govai_chat_requests_total",
    "Total number of chat requests",
    ["agent_id", "lane", "stream", "status"]
)

# Counter: Gate Failures
# Labels: agent_id, reason (no_hits, low_evidence, policy_conflict, temp_gate_fail, missing_context)
GATE_FAIL_TOTAL = Counter(
    "govai_gate_fail_total",
    "Total number of gate/policy failures",
    ["agent_id", "reason"]
)

# Counter: AuthZ Denials
# Labels: agent_id, reason, stream
AUTHZ_DENIALS_TOTAL = Counter(
    "govai_authz_denials_total",
    "Total number of authorization denials",
    ["agent_id", "reason", "stream"]
)

# Counter: Handoffs
# Labels: from_agent, to_agent, reason, auto_redirect (true/false)
HANDOFF_TOTAL = Counter(
    "govai_handoff_total",
    "Total number of conversation handoffs",
    ["from_agent", "to_agent", "reason", "auto_redirect"]
)

# Counter: Rate Limit Blocks
# Labels: type (rps, inflight, stream_concurrent, redis_down_failopen)
RATE_LIMIT_BLOCK_TOTAL = Counter(
    "govai_rate_limit_blocks_total",
    "Total number of rate limit blocks",
    ["type"]
)

# Counter: Stream Disconnects (Explicit tracking)
STREAM_DISCONNECT_TOTAL = Counter(
    "govai_stream_disconnect_total",
    "Total number of client disconnects during stream",
    ["agent_id", "lane"]
)

# Histogram: Latency
# Labels: agent_id, lane, stream
# Buckets: Gov specific (sub-second focus + outlier tracking)
CHAT_LATENCY_SECONDS = Histogram(
    "govai_chat_latency_seconds",
    "End-to-end chat request latency in seconds",
    ["agent_id", "lane", "stream", "stage"], # stage: total, ttft (time to first token - optional)
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
)

# Gauge: Active Streams
# No labels to keep cardinality low and avoid stuck series
STREAMS_ACTIVE = Gauge(
    "govai_streams_active",
    "Number of currently active streaming connections (all tenants)",
    []
)

# Correction: Since I cannot edit chat.py and metrics.py simultaneously easily without breaking tests if I mismatch,
# I will define STREAMS_ACTIVE with `tenant_id` label IF `chat.py` relies on it?
# In PR-D, I added `STREAMS_ACTIVE.labels(tenant_id=tenant_id).inc()`.
# So I *must* support it or change `chat.py` immediately.
# I will change `chat.py` to remove labels in the Instrumentation step (3.1).
# For now I define it WITHOUT labels as per PR7 spec.
INFLIGHT_ACTIVE = Gauge(
    "govai_inflight_active",
    "Number of concurrent requests in flight",
    ["lane"]
)


# ----------------------------------------------------------------------
# 2. Helper Functions
# ----------------------------------------------------------------------
def make_safe_label(s: Optional[str]) -> str:
    return str(s or "unknown").strip().lower()

