# Mesh Retry Amplification Investigation

## Symptoms

- Retry rate climbs faster than raw request volume
- Backpressure shows up in downstream queues or worker pools
- One service may appear overloaded only because retries multiplied load
- Cross-zone or endpoint-fallback behavior often changes at the same time

## Diagnostics

- Compare mesh retry rate with end-user request rate
- Inspect routing policy, timeout budgets, and endpoint selection changes
- Check whether retries arrive after the upstream deadline is already mostly spent
- Look for overflow or retry budget exhaustion warnings in sidecar logs

## Common Causes

- Retry count too high for the end-to-end budget
- Cross-zone fallback adding hidden latency
- Local endpoint scarcity interacting with aggressive retries
- Route changes that increase duplicate work on stateful services

## Recommended Actions

- Tie retries to remaining end-to-end deadline
- Prefer fast failover over repeated cross-zone retries in degraded capacity scenarios
- Expose retry amplification as a first-class incident signal
