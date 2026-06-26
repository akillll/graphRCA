# Consistency Failure Investigation

## Symptoms

- Customers complete a write action successfully but subsequent reads disagree
- Missing or outdated authorization or entitlement state
- Errors often look like not-found or permission denied instead of infrastructure failure
- Cache misses make the inconsistency more visible

## Diagnostics

- Confirm whether the write path actually succeeded
- Compare primary and replica state freshness
- Check for asynchronous propagation, caches, and read-routing behavior
- Review operational jobs that may change write pressure or ordering assumptions

## Common Causes

- Replica lag
- Delayed event propagation
- Cache invalidation gaps
- Read-after-write assumptions violated by optimization changes

## Recommended Actions

- Add read-after-write guardrails for freshness-sensitive paths
- Instrument stale-read indicators directly
- Validate consistency-sensitive changes under concurrent batch-job load
