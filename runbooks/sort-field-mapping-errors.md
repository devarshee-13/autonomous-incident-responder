# Runbook: KeyError in Sort/Field Mapping Dictionaries

## Symptoms
- KeyError raised when looking up a sort/field/option name in a static
  mapping dictionary (e.g. SORT_FIELD_MAP, FILTER_MAP)
- Usually affects a large fraction of traffic if the missing key is a
  common default value

## Likely causes
- A recent refactor of the mapping dictionary accidentally dropped an
  entry that's still referenced elsewhere (often the default option)

## Immediate mitigation
1. Roll back the commit that modified the mapping dictionary
2. If rollback isn't immediately possible, patch the dictionary to restore
   the missing entry, or use `.get(key, default)` instead of `[key]`

## Follow-up
- Add a test asserting the mapping dictionary contains all values the
  default/config options can produce
