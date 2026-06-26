# Cache Degradation Investigation

## Symptoms

- Rising read latency on cache-backed APIs
- Increased cache miss ratio
- Secondary database or origin traffic increase
- Mixed success and timeout behavior rather than a full outage

## Diagnostics

- Compare cache hit rate against request latency and error rate
- Check whether Redis or memcached node health is actually degraded
- Review recent cache TTL, keying, warmup, and invalidation changes
- Inspect whether misses precede downstream database saturation

## Common Causes

- TTL reduction causing churn
- Cache warmup or refresh jobs disabled
- Key format changes creating cold-cache behavior
- Partial cache node failure or network partition

## Recommended Actions

- Roll back recent cache policy changes if hit rate collapsed after deploy
- Protect expensive reads with degraded-mode behavior
- Alert on miss-ratio spikes even when cache node health remains green
