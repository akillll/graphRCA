# Queue Scaling Investigation

## Symptoms

- Queue depth grows while autoscaler reports normal conditions
- Message age rises faster in one shard or partition than others
- Worker CPU looks busy but not catastrophically high
- Partial tenant impact instead of universal delay

## Diagnostics

- Compare the autoscaler's observed signal with actual backlog and message age
- Break queue metrics down by shard, tenant, or partition
- Review recent autoscaler logic and threshold changes
- Check for operational events that skew traffic distribution

## Common Causes

- Averaging away hot-shard pressure
- Scaling on the wrong queue metric
- Delayed metric ingestion to the autoscaler
- Tenant migration or partition rebalance creating skew

## Recommended Actions

- Scale on total backlog plus oldest-message-age, not only averaged shard depth
- Add hot-shard simulation to autoscaler testing
- Alert on large divergence between true backlog and autoscaler-observed backlog
