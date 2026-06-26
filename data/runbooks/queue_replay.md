# Queue Replay Investigation

## Symptoms

- Duplicate candidate rate climbs after failover or consumer rebalance
- Downstream systems report repeated work or deduplication misses
- Broker health may look acceptable while consumers still behave pathologically
- Queue lag and replay side effects propagate into unrelated product surfaces

## Diagnostics

- Distinguish producer duplication from consumer replay using producer-side metrics
- Inspect checkpoint, epoch, and offset-restoration behavior during failover
- Compare duplicate rates with dedup cache effectiveness and downstream queue growth
- Review recent consumer recovery or checkpoint commits

## Common Causes

- Offset checkpoint replay after failover
- Epoch divergence between mirrored and local checkpoint stores
- Dedup cache saturation hiding the original source of duplication
- Long rebalance windows causing repeated range reprocessing

## Recommended Actions

- Test failover with real offset monotonicity assertions
- Alert on checkpoint divergence and replay rate
- Ensure duplicate suppression can absorb failover bursts without eviction collapse
