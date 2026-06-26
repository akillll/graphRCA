# Notification Backlog Investigation

## Symptoms

- Push or email delivery delays affecting only some tenants
- Increased retries from workers even when provider probes look healthy
- Support reports about late but eventually delivered notifications
- Queue age higher on a subset of shards

## Diagnostics

- Distinguish provider slowdown from queue-local throughput problems
- Compare provider synthetic checks against worker-side retries
- Inspect recent shard mapping, tenant migration, and autoscaling changes
- Check whether worker replicas actually increased when backlog rose

## Common Causes

- Hot shard after tenant remap
- Autoscaler not reacting to skewed load
- Provider throttling isolated to one channel
- Worker lease expirations caused by under-capacity

## Recommended Actions

- Expose tenant and shard dimensions in notification dashboards
- Validate autoscaling against skewed traffic patterns
- Keep provider probes separate from worker backlog signals
