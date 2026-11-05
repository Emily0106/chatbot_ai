# Runbook: GateBreachAttemptPolicyConflict

## Metadata
* **Alert Name**: GateBreachAttemptPolicyConflict
* **Severity**: Warning (Security)
* **Threshold**: > 5 events/5m
* **Affected Service**: `gov-ai-backend`

## Symptoms
* Non-compliant queries being rejected.
* Users complaining about "Access Denied" or "Policy Refusal".

## Diagnosis
1. Analyze Queries:
   Check logs for `reason="policy_conflict"`.
   Are users trying to access restricted docs?
   Is it a misconfiguration of user Clearance Level?

## Mitigation
1. If Misconfiguration: Update User Security Level or Doc classification.
2. If Malicious: Lock user account.

## Escalation
* Security Team.
