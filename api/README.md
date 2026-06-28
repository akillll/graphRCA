# API

This package exposes GraphRCA functionality over HTTP.

Scope:

- application configuration
- request and response contracts
- service-layer orchestration
- route handlers for investigation and graph inspection
- normalized API error handling

Suggested flow:

1. Accept a request at the route layer.
2. Validate and normalize the request payload.
3. Call the service layer to run retrieval and prompting.
4. Convert the result into a stable API response model.
5. Return structured errors when graph or model dependencies fail.

## Prerequisites

- Neo4j must be running and reachable with the values in `.env`.
- The local `llama.cpp` server must be running for `POST /investigate`.
- These smoke checks are API-only and independent from Chainlit.

## Run The API

```bash
uvicorn api.app:app --reload
```

Assume:

```bash
export API_BASE_URL="http://127.0.0.1:8000"
```

## Smoke Checks

### Health

```bash
curl "$API_BASE_URL/health"
```

### Graph Stats

```bash
curl "$API_BASE_URL/graph/stats"
```

Include label counts:

```bash
curl "$API_BASE_URL/graph/stats?include_label_counts=true"
```

### Graph Incident Inspection

Easy incident:

```bash
curl "$API_BASE_URL/graph/incident/easy_cache_warmup_regression_2026_04_21"
```

Hard incident:

```bash
curl "$API_BASE_URL/graph/incident/hard_service_mesh_timeout_chain_2026_03_07"
```

Missing incident example:

```bash
curl "$API_BASE_URL/graph/incident/does_not_exist_2026_01_01"
```

### Investigate

Easy incident question:

```bash
curl -X POST "$API_BASE_URL/investigate" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why did catalog-api latency spike on April 21?"
  }'
```

Easy incident question anchored to a known incident ID:

```bash
curl -X POST "$API_BASE_URL/investigate" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why did catalog-api latency spike on April 21?",
    "incident_id": "easy_cache_warmup_regression_2026_04_21",
    "include_debug": true
  }'
```

Hard incident question:

```bash
curl -X POST "$API_BASE_URL/investigate" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What caused the distributed timeout chain in checkout on March 7?"
  }'
```

Unknown incident / no-candidate example:

```bash
curl -X POST "$API_BASE_URL/investigate" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why did the unicorn-billing edge cluster fail on January 1?"
  }'
```

## What To Check

- `GET /health` should return a simple liveness payload.
- `GET /graph/stats` should return graph counts if Neo4j is available.
- `GET /graph/incident/{incident_id}` should return nodes, edges, hypotheses, runbooks, and warnings.
- `POST /investigate` should return an `answer` plus `citations` when Neo4j and `llama.cpp` are both available.
- Unknown incidents or unresolved questions should return a clean JSON error envelope rather than a stack trace.
