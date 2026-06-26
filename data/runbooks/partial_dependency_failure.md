# Partial Dependency Failure Investigation

## Symptoms

- Application logs show timeouts to a dependency, but only some requests fail
- Synthetic or global dependency checks remain healthy
- Error rate is skewed by zone, pod set, or node pool
- Users experience intermittent rather than total failure

## Diagnostics

- Break down failure metrics by zone, shard, node group, or pod label
- Compare application failures with independent dependency probes
- Look for network policy, routing, service mesh, or node-placement changes
- Inspect packet drops or connection reset counters near incident onset

## Common Causes

- AZ-specific network regression
- Service mesh policy mismatch on a subset of nodes
- Partial DNS or routing blackhole
- Security group or network policy drift

## Recommended Actions

- Add locality-aware probes instead of relying on one global health check
- Alert on strong skew by zone or pool
- Review partial-failure hypotheses before blaming the dependency globally
