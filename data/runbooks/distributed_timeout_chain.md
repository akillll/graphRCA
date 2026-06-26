# Distributed Timeout Chain Investigation

## Symptoms

- Several services exceed latency budgets in sequence
- The service closest to the user often looks guilty even when it is only last in the chain
- Retries, queue depth, or canceled requests increase across multiple hops
- Some dependencies remain healthy and help eliminate false leads

## Diagnostics

- Build a hop-by-hop latency timeline rather than investigating each service in isolation
- Compare retry rates, timeout budgets, and deadline cancellations across services
- Check whether control-plane changes altered routing, retry, or fallback behavior
- Identify which metric moved first and which services degraded later as consequences

## Common Causes

- Mesh retry amplification
- Cross-zone or cross-region routing changes
- Local saturation turning into global timeout propagation
- Deadline mismatches between upstream and downstream services

## Recommended Actions

- Use end-to-end budgets to constrain per-hop retries
- Add cross-service waterfall dashboards
- Treat healthy probes in one dependency as evidence to eliminate misleading hypotheses
