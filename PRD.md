# Technical PRD - GraphRCA

## GraphRAG-Powered Incident Root Cause Analysis System

**Version:** 1.1  
**Status:** Design ready for implementation  
**Target Build Window:** Weekend assessment  
**Hardware Target:** MacBook Air M1, 8GB RAM  
**Primary Graph Contract:** `GRAPH_SPEC.md`

## 1. Overview

### 1.1 Problem Statement

Incident responders manually correlate logs, metrics, deployments, commits, runbooks, and operational context across disconnected systems. The investigation is slow, prone to anchoring bias, and rarely preserves why competing hypotheses were accepted or rejected.

### 1.2 Product Goal

GraphRCA builds a local evidence graph from a benchmark incident dataset. At query time it traverses the graph, gathers evidence across sources, enriches the result with local vector retrieval, and generates an RCA using a local llama.cpp model.

The output must show:

- the evidence neighborhood traversed
- hypotheses considered
- hypotheses supported or ruled out
- citations to graph nodes
- confidence rationale
- recommended actions when supported by runbooks or evidence

### 1.3 Core Thesis

Incidents are naturally graph-shaped. A useful RCA depends on relationships: what changed, when symptoms began, which services were involved, which metrics moved first, which log patterns appeared, and what runbooks match the symptoms.

Traditional vector RAG retrieves text chunks, but it does not preserve temporal ordering, service relationships, or evidence provenance. GraphRCA uses graph traversal as the primary retrieval mechanism and vector search only to enrich the traversed evidence with semantically relevant runbook or log context.

### 1.4 Non-Negotiable Boundary

`expected_rca.json` is evaluation-only. It must never be ingested into the runtime graph.

Runtime answers must be generated from:

- `metadata.json`
- `deployments.json`
- `commits.json`
- `metrics.json`
- `logs.json`
- `timeline.json`
- `runbooks/*.md`
- optional lightweight topology additions

## 2. Goals and Non-Goals

### 2.1 Goals

- Build a locally runnable GraphRAG system using Neo4j, FastAPI, Chainlit, llama.cpp, and local embeddings.
- Ingest the current 12-incident benchmark dataset into an evidence-oriented graph.
- Use deterministic canonical IDs for idempotent graph construction.
- Avoid deterministic causal truth edges during ingestion.
- Retrieve evidence primarily through Cypher graph traversal.
- Use vector search to enrich graph results with relevant runbook/log context.
- Generate RCA responses with node-level citations.
- Make hypothesis support and elimination visible.
- Evaluate against benchmark ground truth without leaking ground truth into runtime.

### 2.2 Non-Goals

- Real-time ingestion or live observability integrations.
- External API calls to CloudWatch, Datadog, PagerDuty, or hosted LLMs.
- Multi-tenant authentication.
- ReAct-style dynamic tool loops.
- Full production deployment hardening.
- Frontend graph visualization beyond readable Chainlit steps.
- Manual ingestion of final RCA ground truth.

## 3. Current Dataset

### 3.1 Dataset Layout

```text
data/
  incidents/
    easy/
      db_pool_exhaustion/
      cache_warmup_regression/
      webhook_retry_amplification/
      redis_tls_misconfig/
    medium/
      media_worker_memory_leak/
      replica_lag_entitlements/
      queue_autoscaling_regression/
      az_egress_policy_regression/
    hard/
      gateway_reconnect_storm/
      feature_flag_cache_stampede/
      service_mesh_timeout_chain/
      cross_region_queue_replay_storm/
  runbooks/
    *.md
  evaluations/
    benchmark_easy.json
    benchmark_medium.json
    benchmark_hard.json
```

### 3.2 Benchmark Incidents

| Tier | Incident ID | Service | Severity |
|---|---|---|---|
| Easy | `easy_db_pool_exhaustion_2026_05_14` | `checkout-api` | `sev-2` |
| Easy | `easy_cache_warmup_regression_2026_04_21` | `catalog-api` | `sev-2` |
| Easy | `easy_webhook_retry_amplification_2026_03_03` | `webhook-dispatcher` | `sev-2` |
| Easy | `easy_redis_tls_misconfig_2026_02_11` | `session-api` | `sev-2` |
| Medium | `medium_media_worker_memory_leak_2026_05_22` | `media-worker` | `sev-2` |
| Medium | `medium_replica_lag_entitlements_2026_04_09` | `entitlements-api` | `sev-2` |
| Medium | `medium_queue_autoscaling_regression_2026_03_18` | `notification-worker` | `sev-2` |
| Medium | `medium_az_egress_policy_regression_2026_02_27` | `auth-api` | `sev-2` |
| Hard | `hard_gateway_reconnect_storm_2026_05_03` | `realtime-gateway` | `sev-1` |
| Hard | `hard_feature_flag_cache_stampede_2026_04_14` | `feature-flag-control-plane` | `sev-1` |
| Hard | `hard_service_mesh_timeout_chain_2026_03_07` | `checkout-orchestrator` | `sev-1` |
| Hard | `hard_cross_region_queue_replay_storm_2026_01_18` | `event-ingestion-pipeline` | `sev-1` |

### 3.3 Per-Incident Files

Each incident contains:

| File | Runtime Use |
|---|---|
| `metadata.json` | Incident metadata, candidate hypotheses, relevant runbooks, operational context, affected services |
| `deployments.json` | Deployment, rollback, or maintenance events |
| `commits.json` | Recent commits and changed files |
| `metrics.json` | Metric time series observed around the incident |
| `logs.json` | Raw log events |
| `timeline.json` | Human-readable event sequence |
| `services.json` | Hard-incident service aliases and dependency topology |
| `expected_rca.json` | Evaluation-only ground truth |

### 3.4 Dataset Observations

- Medium and hard incidents include `operational_context`.
- Hard incidents include `affected_services`.
- Hard incidents include `services.json` topology with service aliases and dependencies.
- Deployment records include explicit `commit_ids` arrays for deterministic commit-to-deployment edges.
- Metric series include explicit `service` ownership for deterministic metric-to-service edges.
- All current `expected_rca.json` files have `confidence: high`, so medium/low confidence behavior needs simulated missing-evidence tests or future lightweight fixtures.

## 4. Graph Model

The graph model is specified in `GRAPH_SPEC.md`.

Implementation must follow these principles:

- use canonical IDs for every node
- create deterministic nodes and edges from structured files
- mark LLM-assisted nodes and edges with provenance
- avoid ingesting final RCA labels into runtime graph
- model evidence with relationships such as `OBSERVED_IN`, `OBSERVED_ON`, `OCCURRED_AFTER`, `CHANGED`, `MATCHES`, `SUPPORTS`, `RULES_OUT`, `REFERENCES`, and `RECOMMENDS`
- avoid asserting `CAUSED` during ingestion

### 4.1 Required Runtime Node Types

- Incident
- Service
- Deployment
- Commit
- Metric
- MetricSeries
- LogEvent
- LogPattern
- Runbook
- Hypothesis
- Configuration
- Action
- TimelineEvent

### 4.2 Required Runtime Edge Types

- OBSERVED_IN
- OBSERVED_ON
- OCCURRED_AFTER
- DEPENDS_ON
- CHANGED
- INCLUDED_IN
- MATCHES
- SUPPORTS
- RULES_OUT
- REFERENCES
- RECOMMENDS

## 5. System Architecture

### 5.1 Stack

| Layer | Technology | Reason |
|---|---|---|
| Graph DB | Neo4j 5.x | Native graph traversal and Cypher |
| Local LLM | llama.cpp, small quantized model | Runs locally on M1 hardware |
| Embeddings | local sentence-transformer | Lightweight semantic retrieval |
| Backend | FastAPI | Simple API and OpenAPI support |
| UI | Chainlit | Step-based investigation display |
| Runtime | Docker Compose | One-command local demo |

### 5.2 Recommended Codebase Layout

The following structure is a good fit for the weekend build because it separates deterministic parsing, LLM-assisted enrichment, graph retrieval, prompt construction, API wiring, and offline evaluation without introducing too many layers:

```text
graphRCA/
├── ingestion/
│   ├── deterministic/
│   │   ├── metadata.py
│   │   ├── deployments.py
│   │   ├── commits.py
│   │   ├── metrics.py
│   │   ├── logs.py
│   │   └── timeline.py
│   └── llm/
│       ├── log_patterns.py
│       ├── hypothesis_scoring.py
│       └── runbook_matching.py
├── retrieval/
├── prompting/
├── api/
└── evaluation/
```

Responsibilities:

- `ingestion/deterministic/`: parse source files into canonical nodes and deterministic edges
- `ingestion/llm/`: semantic extraction that adds provenance-tagged nodes or edges
- `retrieval/`: Neo4j access, Cypher queries, graph traversal, neighborhood expansion, and evidence assembly
- `prompting/`: structured prompt builders for entity extraction and RCA generation
- `api/`: FastAPI routes, response schemas, and app wiring
- `evaluation/`: benchmark runners and scoring against `expected_rca.json`

Implementation note:

- Keep graph-specific code such as Neo4j client setup, Cypher query helpers, and traversal orchestration in `retrieval/` or a small shared graph module. Do not bury database concerns inside the ingestion parsers.

### 5.3 Architecture Flow

```text
Incident JSON + runbooks
  -> deterministic ingestion
  -> LLM-assisted semantic extraction
  -> Neo4j evidence graph
  -> local vector index for runbook/log enrichment
  -> query entity extraction
  -> graph traversal
  -> evidence aggregation
  -> vector enrichment
  -> llama.cpp RCA generation
  -> FastAPI + Chainlit response
```

### 5.4 Query Flow

```text
User question
  -> extract incident/service/symptom/time entities
  -> find matching incident or service nodes
  -> traverse evidence neighborhood
  -> aggregate deployments, commits, metrics, logs, runbooks, context
  -> retrieve relevant runbook passages
  -> assemble structured prompt
  -> generate RCA with citations
```

## 6. Ingestion Requirements

### 6.1 Deterministic Extraction

Deterministic parsers should handle:

- incident metadata
- services explicitly named in metadata, deployments, logs, and affected service arrays
- deployments and rollback/maintenance events
- commits and changed files
- metric identities and incident-scoped metric series
- raw log events
- timeline events
- explicit relevant runbook references

### 6.2 LLM-Assisted Extraction

Use LLM assistance only where it has clear value:

- grouping raw logs into semantic `LogPattern` nodes
- extracting runbook actions when headings or prose vary
- matching runbooks to symptoms beyond explicit metadata links
- proposing `SUPPORTS` and `RULES_OUT` edges for candidate hypotheses
- mapping timeline prose to known evidence nodes

LLM outputs must be structured, validated, and tagged with provenance.

### 6.3 Ground Truth Exclusion

Do not ingest:

- `expected_rca.root_cause`
- `expected_rca.confidence`
- `expected_rca.evidence_sources`
- `expected_rca.expected_investigation_path`
- `expected_rca.recommended_actions`

Those fields are only for offline evaluation.

## 7. Retrieval Requirements

### 7.1 Graph-First Retrieval

Given a user query, the system should:

1. Identify the likely incident, service, symptom, or time window.
2. Traverse from the incident/service into the evidence neighborhood.
3. Retrieve observed deployments, commits, metrics, logs, timeline events, candidate hypotheses, operational context, and runbooks.
4. Expand only one to two hops around high-signal evidence.
5. Return compact structured evidence with node IDs and edge types.

### 7.2 Vector Enrichment

Vector retrieval should:

- search runbook passages
- search semantic log pattern summaries
- enrich the graph neighborhood with explanatory context

Vector retrieval should not:

- replace graph traversal
- invent missing service topology
- override graph evidence
- generate citations that do not map back to graph nodes

## 8. API Requirements

### 8.1 `POST /investigate`

Request:

```json
{
  "question": "Why did catalog-api latency spike on April 21?"
}
```

Response:

```json
{
  "answer": "...",
  "confidence": "high",
  "confidence_rationale": "...",
  "traversal_path": [],
  "evidence_nodes": [],
  "hypotheses": {
    "supported": [],
    "ruled_out": []
  },
  "citations": []
}
```

### 8.2 `GET /graph/stats`

Returns node counts, edge counts, incident coverage, and ingestion status.

### 8.3 `GET /graph/incident/{incident_id}`

Returns the incident-centered evidence subgraph for UI display and debugging.

## 9. Chainlit UI Requirements

The UI should show four visible investigation steps:

1. **Entities extracted**
   - incident ID, service names, symptoms, time references

2. **Graph traversal**
   - readable path or neighborhood summary with node IDs and edge types

3. **Hypothesis evaluation**
   - supported hypotheses
   - ruled-out hypotheses
   - evidence citations for each

4. **RCA generation**
   - final answer
   - evidence trail
   - confidence rationale
   - recommended actions when supported

The UI should optimize for clarity of investigation, not visual polish.

## 10. Evaluation

### 10.1 Evaluation Inputs

Use the benchmark files:

- `data/evaluations/benchmark_easy.json`
- `data/evaluations/benchmark_medium.json`
- `data/evaluations/benchmark_hard.json`

Use each incident's `expected_rca.json` only after the runtime system has produced an answer.

### 10.2 Metrics

**RCA correctness**

Compare the generated explanation to `expected_rca.root_cause`.

**Evidence recall**

Check whether cited evidence covers the expected source categories from `expected_rca.evidence_sources`.

**Traversal accuracy**

Compare the traversal result against `expected_rca.expected_investigation_path` at a step/source-category level. The current ground truth is natural language, not exact graph paths.

**Citation quality**

Every citation should reference a graph node that exists and accurately supports the cited claim.

**Hypothesis handling**

The answer should use `metadata.primary_hypotheses` as candidates and show which are supported or ruled out.

**Confidence calibration**

The answer should reduce confidence when graph traversal misses key source categories. The current dataset only contains high-confidence ground truth, so evaluation should include missing-evidence simulations for low/medium confidence behavior.

### 10.3 Initial Targets

| Tier | Evidence Recall | Citation Validity | Hypothesis Handling |
|---|---:|---:|---:|
| Easy | 0.90 | 0.95 | 0.80 |
| Medium | 0.80 | 0.90 | 0.75 |
| Hard | 0.70 | 0.85 | 0.70 |

## 11. Minimal Dataset Additions

Do not redesign the dataset. Additions should be optional and lightweight.

### 11.1 Highest Value: `services.json`

Hard incidents include per-incident topology where distributed reasoning matters most.

Minimal format:

```json
{
  "services": [
    {"name": "checkout-orchestrator", "type": "api"},
    {"name": "pricing-api", "type": "api"}
  ],
  "dependencies": [
    {"from": "checkout-orchestrator", "to": "pricing-api", "relationship": "calls"}
  ]
}
```

Runtime effect:

- deterministic `Service` nodes
- deterministic `DEPENDS_ON` edges

### 11.2 Useful: Deployment Commit Mapping

Deployment records include `commit_ids` when exact release membership is known. Empty arrays are valid for rollback or operational events with no associated commit in the fixture.

Runtime effect:

- deterministic `Commit -> Deployment` `INCLUDED_IN` edges

### 11.3 Useful: Metric Service Ownership

Metric series include `service`.

Runtime effect:

- deterministic `MetricSeries -> Service` `OBSERVED_ON` edges

### 11.4 Evaluation-Only: Expected Evidence Nodes

Add optional `expected_evidence_nodes` to `expected_rca.json` for deterministic scoring.

Runtime effect:

- none

This field must remain evaluation-only.

## 12. Weekend Build Plan

### Phase 0 - Scaffold

- Docker Compose with Neo4j, backend, and Chainlit service definitions.
- Local llama.cpp configuration documented.
- `.env.example` with Neo4j and model settings.

### Phase 1 - Graph Contract and Client

- Implement graph schema constants from `GRAPH_SPEC.md`.
- Add Neo4j client and indexes on canonical IDs.
- Add smoke test for one incident node.

### Phase 2 - Deterministic Ingestion

- Parse all incident files except `expected_rca.json`.
- Parse runbooks.
- Create canonical nodes and deterministic edges.
- Confirm all 12 incidents appear in graph stats.

### Phase 3 - Minimal LLM-Assisted Extraction

- Extract log patterns.
- Extract runbook actions if needed.
- Generate hypothesis `SUPPORTS` and `RULES_OUT` edges with provenance.

### Phase 4 - GraphRAG Query Engine

- Entity extraction.
- Incident/service lookup.
- Evidence neighborhood traversal.
- Vector enrichment for runbooks.
- Structured prompt assembly.
- RCA generation with citations.

### Phase 5 - API and UI

- `POST /investigate`
- `GET /graph/stats`
- `GET /graph/incident/{incident_id}`
- Chainlit four-step investigation display.

### Phase 6 - Evaluation and README

- Run all 12 benchmark incidents.
- Report evidence recall, citation validity, and hypothesis handling.
- Document known limitations.

## 13. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Dataset lacks topology for hard incidents | High | Add optional `services.json`; otherwise fall back to `affected_services` without dependency direction |
| Commit-to-deployment mapping is ambiguous | Medium | Label as incident-window association unless `commit_ids` are added |
| LLM extraction produces malformed JSON | Medium | Validate schema, retry, and continue with deterministic graph |
| Local llama.cpp is slow | Medium | Use compact context, cache repeated queries, keep model small |
| Confidence evaluation is weak | Medium | Simulate missing evidence because current expected labels are all high |
| Overbuilding the architecture | Medium | Prioritize graph correctness, citations, and hypothesis elimination over polish |

## 14. Definition of Done

The assessment is successful when:

- docs match the actual dataset
- graph construction is deterministic and replayable
- `expected_rca.json` is excluded from runtime ingestion
- all 12 incidents can be ingested
- queries return evidence-backed RCAs
- answers cite graph node IDs
- hypotheses are visibly supported or ruled out
- evaluation can score against benchmark files
- the local demo runs on M1 hardware within practical time limits
