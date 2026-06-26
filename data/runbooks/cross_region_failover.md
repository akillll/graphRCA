# Cross Region Failover Investigation

## Symptoms

- Regional traffic shifts followed by unexpected duplicates, lag, or partial degradation
- Primary network symptoms may disappear while application symptoms continue
- Mirrored state stores and checkpoint systems disagree temporarily
- Downstream services degrade after the traffic move rather than during the network event itself

## Diagnostics

- Separate the trigger event from the sustaining fault
- Check whether failover exercised rarely used checkpoint, mirror, or replay logic
- Compare region-shift timing with consumer group, queue, and dedup metrics
- Inspect whether rollback restores convergence without requiring network recovery

## Common Causes

- Checkpoint replay bugs
- Mirror lag or epoch mismatch
- Incomplete idempotency under failover bursts
- Automation that shifted traffic faster than state convergence

## Recommended Actions

- Drill real failovers regularly
- Keep mirrored state semantics simple and monotonic
- Monitor post-failover replay indicators, not just network health
