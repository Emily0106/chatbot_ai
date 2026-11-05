# Runbook: HighErrorRate

## Metadata
* **Alert Name**: HighErrorRate
* **Severity**: Critical
* **Threshold**: > 10% failures (5m window)
* **Affected Service**: `gov-ai-backend`

## Symptoms
* Users report "Server Error" or "Connection Failed".
* P95 Latency might spike.

## Diagnosis
1. Check Logs:
   ```bash
   docker logs gov-ai-backend --tail 100
   ```
   Look for `500 Internal Server Error`, `Connection Refused`, or `Database Error`.

2. Check Database:
   Is Postgres/Qdrant reachable?

3. Check Dependencies:
   Is the LLM Provider API down?

## Mitigation
1. If LLM Provider down: Enable "Degraded Mode" (if available) or update Status Page.
2. If Database overload: Restart DB or Scale up.
3. If Bug: Rollback to previous version.

## Escalation
* PagerDuty: @backend-oncall
