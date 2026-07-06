# Runbook: Downstream/Third-Party Provider Outages

## Symptoms
- Errors originate inside a third-party client library (e.g. smtplib,
  a payment gateway SDK, a cloud provider SDK), not application code
- No recent deploy plausibly explains the failure — error started
  independent of any deploy timeline
- Often connection-level errors: timeouts, disconnects, 5xx from the
  provider

## Likely causes
- The third-party provider is having an outage or degraded performance
- Network issue between our service and the provider
- Provider-side rate limiting

## Immediate mitigation
1. Check the provider's public status page
2. Check for existing retry/circuit-breaker logic around the failing
   client — enable or tighten it if not already active
3. If a queueable/deferrable operation (e.g. email), let it retry/backoff
   rather than treating it as user-facing failure

## Follow-up
- Add explicit alerting to distinguish "our code broke" from "a
  downstream dependency broke", so on-call doesn't chase an internal
  root cause that doesn't exist
