# Runbook: HighLatencyP95

## Metadata
* **Alert Name**: HighLatencyP95
* **Severity**: Warning
* **Threshold**: P95 > 3s (5m window)
* **Affected Service**: `gov-ai-backend`

## Symptoms
* Sluggish response.
* Timeouts in client.

## Diagnosis
1. Identify Slow Component:
   Check `govai_chat_latency_seconds_bucket` histogram.
   Is it LLM, RAG (Retrieval), or Processing?

2. Check Resource Usage:
   CPU/Memory on Backend or Database/VectorDB.

## Mitigation
1. If RAG slow: Check Qdrant performance/indices.
2. If LLM slow: Nothing internal; consider switching provider model if multi-model supported.
3. If Compute bound: Scale replicas.

## Escalation
* Slack: #backend-performance
