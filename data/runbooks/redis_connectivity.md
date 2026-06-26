# Redis Connectivity Investigation

## Symptoms

- Session or cache operations failing quickly
- Connection reset, EOF, or handshake errors in application logs
- Elevated application 5xx rate with low request latency
- Inconsistent assumptions about TLS, auth, or network path

## Diagnostics

- Compare client-side failures with Redis server CPU, connected clients, and failover state
- Check recent changes to TLS, auth credentials, ports, and client libraries
- Inspect VPC or node-level reset metrics for protocol mismatch patterns
- Validate whether a rollback restores normal read and write success

## Common Causes

- TLS enabled on the client but not on the server
- Wrong port or auth secret
- Network ACL or security group regression
- Redis node failover or unavailability

## Recommended Actions

- Revert transport changes that were not enabled end-to-end
- Add canary read/write checks that run with deployed client settings
- Document environment-specific Redis transport requirements
