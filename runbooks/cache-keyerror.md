# Runbook: Cache Lookup KeyError / Cache-Related Errors

## Symptoms
- KeyError raised from a dict-based in-process cache lookup
- Often follows a deploy that switched a code path from an API/DB call to
  a local cache read

## Likely causes
- A recent deploy assumes the cache is always populated for a given key,
  but the cache can miss (cold start, eviction, key not yet warmed)

## Immediate mitigation
1. Roll back the deploy that introduced the unguarded cache read, or
2. Patch forward: add a `.get(key, default)` / fallback path for cache misses

## Follow-up
- Add cache-miss metrics and alerting so this class of bug surfaces faster
  next time
