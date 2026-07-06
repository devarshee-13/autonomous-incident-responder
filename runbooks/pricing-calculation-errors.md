# Runbook: Pricing Calculation Errors (ZeroDivisionError, ValueError)

## Symptoms
- Elevated error rate on checkout/payments endpoints
- ZeroDivisionError or ValueError originating in pricing/discount calculation code
- Often correlated with a recent deploy touching discount or tax calculation logic

## Likely causes
- A recent change to discount or tax percentage math (e.g. dividing by a
  value derived from a percentage) that doesn't guard against edge values
  like 0% or 100%
- Missing input validation on discount_pct/tax_pct fields

## Immediate mitigation
1. Roll back the most recent deploy touching pricing/discount code
2. If rollback isn't immediately possible, add input validation/clamping
   around discount_pct before the affected calculation
3. Monitor error rate for recovery after mitigation

## Follow-up
- Add unit tests covering boundary values (0%, 100%) for any discount/tax math
