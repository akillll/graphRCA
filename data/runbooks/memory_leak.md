# Memory Leak Investigation

## Symptoms

- Gradual latency or backlog increase rather than an instant outage
- Per-pod memory rising steadily across multiple intervals
- Container restarts or OOM kills increasing over time
- CPU may rise mildly but often does not explain the full degradation

## Diagnostics

- Compare memory growth, restart count, queue depth, and CPU over the same window
- Check whether a recent deploy changed object lifetimes, caching, parsing, or fanout behavior
- Rule out downstream latency so the team does not confuse blocked workers with leaked workers
- Look for monotonic memory growth that resets only after restart or rollback

## Common Causes

- Retained buffers or caches after parsing changes
- Unbounded in-memory fanout or aggregation
- Goroutines or threads holding references longer than intended
- Slow leak exposed only under a specific traffic mix

## Recommended Actions

- Roll back the leaking change and capture heap profiles from production-like traffic
- Alert on RSS growth slope and OOM restart acceleration
- Add load tests for long-running worker behavior, not only short benchmark runs
