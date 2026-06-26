# Reconnect Storm Investigation

## Symptoms

- Sudden disconnect surge followed by much larger reconnect or identify traffic
- Multiple downstream dependencies appear unhealthy only after client churn begins
- User-facing symptoms are widespread and often resemble an edge or network outage
- Recovery is slow because retries or reconnects keep the system saturated

## Diagnostics

- Determine whether disconnects, resume failures, or dependency saturation moved first
- Break reconnect behavior down by session cohort, shard, or transfer window
- Check recent rollout changes to resume semantics, identify budgets, and shard movement logic
- Compare edge network health with application-layer reconnect amplification

## Common Causes

- Resume-token invalidation after control-plane movement
- Aggressive reconnect or identify throttling behavior
- Coordinated disconnects during shard migration
- Downstream auth or session dependencies collapsing under reconnect load

## Recommended Actions

- Protect resume paths during controlled shard movement
- Add reconnect storm dampening and dependency budgets
- Avoid overlapping control-plane movement with risky gateway changes
