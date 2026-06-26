# Worker Backlog Investigation

## Symptoms

- Queue depth and oldest-message age climbing
- Customer-visible delays without total request failure
- Retry traffic or requeues increasing
- Autoscaling may appear active but still fail to restore throughput

## Diagnostics

- Check whether backlog is fleet-wide or localized to a subset of workers, shards, or job types
- Compare worker restarts, memory, CPU, and downstream latency
- Review recent scaling-policy or worker-runtime deployments
- Validate whether backlog growth matches ingress growth or reduced effective capacity

## Common Causes

- Worker crashes or OOM kills
- Hot partition or skewed shard traffic
- Misconfigured autoscaling signal
- Dependency slowdown or retry amplification

## Recommended Actions

- Identify whether the problem is capacity, skew, or crash-related before scaling blindly
- Add alarms on oldest-message age and effective worker throughput
- Include shard-level and queue-level views in the same dashboard
