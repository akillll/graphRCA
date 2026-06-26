# Network Policy Investigation

## Symptoms

- Timeouts or incomplete handshakes to internal services after a policy rollout
- Only some pods or zones affected
- Service discovery and endpoint health may still look normal
- Packet drops increase without obvious node resource pressure

## Diagnostics

- Compare policy deployment timing with error onset
- Inspect CNI or dataplane logs for dropped packets by namespace, destination, and port
- Validate policy label selectors against live service identities
- Check whether node rotation or placement changes concentrated traffic onto affected nodes

## Common Causes

- Egress allowlist missing a real dependency
- Label or identity mismatch between policy and service
- Zone-specific node pool drift
- Policy tested only in one environment shape

## Recommended Actions

- Canaries should include real dependency calls from every zone
- Keep label-to-service mappings versioned and validated
- Roll back quickly if dependency probes and zone skew disagree
