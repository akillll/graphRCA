# Database Timeout Investigation

## Symptoms

- API latency spikes accompanied by query timeouts
- Connection acquisition delays or pool waiter growth
- Some requests succeed while others fail under normal traffic
- Database host metrics may remain deceptively healthy

## Diagnostics

- Compare application pool saturation with database host connection usage
- Check recent deployments and config changes affecting pool size, concurrency, or transaction scope
- Inspect whether slow queries precede timeouts or merely appear after connections queue
- Validate whether rollback or config restore clears the issue

## Common Causes

- Application connection pool exhaustion
- Long-running queries
- Connection leaks
- Traffic amplification after cache degradation

## Recommended Actions

- Restore safe pool configuration
- Add alerts for application-side pool waiters
- Review deploy-time config diffs before rollout
