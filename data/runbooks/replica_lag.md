# Replica Lag Investigation

## Symptoms

- Intermittent stale reads or missing state after recent writes
- Authorization, entitlement, or inventory checks disagreeing with successful writes
- Query latency on replicas increasing while primary writes continue succeeding
- Problems concentrated on recently changed records

## Diagnostics

- Compare write success metrics with read-consistency failures
- Measure replica lag and read-routing share at incident onset
- Check for concurrent backfills, reindex jobs, or reconciliation workloads
- Review whether recent deployments increased replica usage for critical reads

## Common Causes

- Write-heavy batch jobs outpacing replica apply rate
- New read-routing logic preferring replicas without freshness guardrails
- Cache misses exposing stale replica reads
- Failover or replication slot pressure

## Recommended Actions

- Route freshness-sensitive reads to primary when lag is elevated
- Add alerts that tie replica lag to stale-read symptoms
- Coordinate batch jobs with services that depend on recent-write consistency
