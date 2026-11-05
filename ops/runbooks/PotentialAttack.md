# Runbook: PotentialAttackRateLimitSpike

## Metadata
* **Alert Name**: PotentialAttackRateLimitSpike
* **Severity**: Critical
* **Threshold**: > 50 blocks/min
* **Affected Service**: `gov-ai-backend`

## Symptoms
* Massive increase in 429 responses.
* Valid users might be blocked if IP shared.

## Diagnosis
1. Check blocked IPs/Tenants:
   Review logs for `RateLimitBlock` events.
   Identify source IP.

2. Verify if DDoS or aggressive legitimate client (e.g. load test).

## Mitigation
1. Block malicious IP at Firewall/Nginx level.
2. Rate Limit Tuning: If legitimate spike, temporarily increase burst limit?
   `RATE_LIMIT_BURST` env var.

## Escalation
* Security Team / Ops Lead.
