# Cache Stampede Investigation

## Symptoms

- Cache hit rate collapses suddenly while backend load climbs sharply
- Retries and stale reads increase across multiple callers
- The database or origin service may appear to be the primary failure even when it is not
- Invalidations or hot-key churn often precede the largest latency spike

## Diagnostics

- Determine whether cache misses started before backend saturation
- Inspect invalidation volume, fill dedupe behavior, and hot namespace or key cardinality
- Compare retry amplification from callers with cache recovery behavior
- Review recent cache invalidation and fill coordination changes

## Common Causes

- Wildcard invalidation or broad key eviction
- Singleflight or dedupe bypass under heavy fanout
- Launch traffic exposing a pathological cache fill pattern
- Clients retrying aggressively on a control-plane timeout

## Recommended Actions

- Preserve stale data or dedupe fills during high-cardinality invalidation
- Alert on the sequence of invalidation spike, miss spike, and backend surge
- Roll back invalidation behavior before tuning the database in a panic
