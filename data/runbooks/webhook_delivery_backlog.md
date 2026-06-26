# Webhook Delivery Backlog Investigation

## Symptoms

- Queue depth rising for outbound deliveries
- Retry rate increasing faster than ingress rate
- Customer notifications delayed or duplicated
- Timeouts concentrated on one partner or endpoint

## Diagnostics

- Compare outbound client timeout values with observed partner latency
- Check whether partner probes show an outage or only slow-but-successful responses
- Review retry policy and recent delivery client changes
- Confirm whether backlog growth began after a deployment

## Common Causes

- Local timeout set below normal partner latency
- Retry policy too aggressive for slow dependencies
- Partner outage or rate limiting
- Worker pool saturation

## Recommended Actions

- Restore sane per-partner timeout values
- Add circuit breaking or capped retries for slow dependencies
- Drain backlog after rollback or config correction
