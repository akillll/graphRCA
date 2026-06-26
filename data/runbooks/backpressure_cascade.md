# Backpressure Cascade Investigation

## Symptoms

- Queues, worker pools, or pending requests grow across several layers
- Some services start dropping or delaying work while upstream continues sending traffic
- Retries and duplicated work make recovery harder than the initial trigger
- Recovery typically lags well behind the first corrective action

## Diagnostics

- Identify which queue or pending-work metric moved first
- Determine whether work increased because of real demand or duplicated/retried demand
- Correlate backpressure with timeout and cancellation signals
- Review any control-plane changes that altered routing, replay, or batching semantics

## Common Causes

- Retry storms
- Replay after failover
- Stateful downstream services receiving duplicate work
- Mis-sized worker pools recovering from a burst

## Recommended Actions

- Shed duplicated or low-priority work early
- Alert on mismatches between ingress rate and successful completion rate
- Track recovery lag explicitly, not just incident onset
