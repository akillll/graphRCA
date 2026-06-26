# Session Store Saturation Investigation

## Symptoms

- Rising session lookup latency and timeout errors
- Session-dependent services report failures, but those may be secondary
- CPU or pipeline wait time increases quickly under bursty reconnect patterns
- Redis or cache health can look normal before traffic amplification starts

## Diagnostics

- Determine whether session-store load is primary or induced by another storm
- Compare incoming lookup rate with normal reconnect and identify volumes
- Check whether failures concentrate on a moving session cohort or shard set
- Review recent changes to session invalidation, resume logic, or shard transfers

## Common Causes

- Reconnect storm from gateway layer
- Session key churn or mass invalidation
- Pipeline timeouts from lookup amplification
- Shard hotspot after control-plane movement

## Recommended Actions

- Alert on session lookup amplification, not just raw latency
- Add read shedding or fallback for storm scenarios
- Trace causality before treating Redis saturation as the root cause
