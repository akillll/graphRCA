# Control Plane Overload Investigation

## Symptoms

- Many product surfaces degrade at once without a single obvious data-plane outage
- Stale configuration, fallback defaults, or delayed propagation appear in different products
- Caller retry rates rise as central resolution services slow down
- Backend databases or caches can show overload as second-order effects

## Diagnostics

- Map which products depend on the control plane and when each began failing
- Compare cache health, request fanout, and retry amplification
- Review recent rollout changes to control-plane invalidation or routing
- Distinguish stale-while-revalidate behavior from a full propagation failure

## Common Causes

- Cache stampedes
- Broad invalidation mistakes
- Retry amplification from many clients
- Control-plane rollout combined with traffic surge

## Recommended Actions

- Keep last-known-good behavior available while isolating the cause
- Add tenant or namespace level load-shedding
- Treat widespread stale defaults as a control-plane dependency symptom
