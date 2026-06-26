# AGENTS.md - GraphRCA

## Project Identity

**GraphRCA** is a local GraphRAG-powered incident investigation system for evidence-based root cause analysis across operational datasets.

The system builds a graph of incident evidence: incidents, services, deployments, commits, metric series, log events, log patterns, runbooks, hypotheses, configuration context, and actions. At query time, it traverses this graph, retrieves supporting evidence, explicitly rules out competing hypotheses, and generates a structured RCA with citations.

This is not a log summarizer. This is not a document chatbot. It is an evidence graph investigator.

## Core Design Principle

The runtime graph represents **evidence relationships**, not assumed truth.

During ingestion, deterministic parsers create factual nodes and factual edges from structured files. LLM-assisted extraction may propose semantic patterns, runbook matches, and evidence relationships, but those relationships must be marked with provenance and extraction method. The system should not ingest final RCA answers as runtime truth.

`GRAPH_SPEC.md` is the single source of truth for graph node types, edge types, canonical IDs, ingestion behavior, traversal behavior, and the dataset contract.

## Product Mission

Reduce mean time to root cause by encoding operational evidence as a traversable graph and reasoning over it in the investigation pattern used by experienced SREs:

```text
observe symptoms
form hypotheses
gather evidence across sources
eliminate what evidence rules out
confirm the strongest evidence-backed explanation
produce a replayable RCA
```

## Core Principles

**1. Show the investigation, not only the conclusion**
Every RCA response must include the graph path or neighborhood used: which nodes were visited, which relationships were followed, and which evidence was cited.

**2. Require evidence before conclusions**
Confidence is based on evidence completeness, not model tone. Strong confidence requires corroboration across multiple evidence types such as deployment timing, commits, metrics, logs, operational context, and runbooks.

**3. Prefer evidence relationships over premature causality**
Runtime ingestion should create relationships such as `OBSERVED_IN`, `OCCURRED_AFTER`, `CHANGED`, `SUPPORTS`, `RULES_OUT`, `MATCHES`, `REFERENCES`, and `RECOMMENDS`. Avoid writing deterministic `CAUSED` edges during ingestion unless the dataset explicitly contains that assertion as evidence.

**4. Multi-source correlation beats single-source pattern matching**
A log pattern alone is not sufficient for a root cause. The system should correlate across at least two source types before presenting a confirmed explanation.

**5. Hypothesis elimination is first-class**
Ruled-out hypotheses should be visible in the response with the evidence that ruled them out. A good answer explains both the likely cause and why plausible alternatives are weaker.

**6. Graph retrieval is primary; vector retrieval enriches**
Cypher traversal should identify the evidence neighborhood. Vector search should add relevant runbook passages or semantically similar log patterns after graph traversal, not replace the graph.

**7. Replayability**
Every investigation should be reproducible from the graph state, query entities, traversal results, retrieved evidence, and final citations.

## Current Dataset

The repository currently contains 12 benchmark incidents:

### Easy

- `easy_db_pool_exhaustion_2026_05_14`
- `easy_cache_warmup_regression_2026_04_21`
- `easy_webhook_retry_amplification_2026_03_03`
- `easy_redis_tls_misconfig_2026_02_11`

### Medium

- `medium_media_worker_memory_leak_2026_05_22`
- `medium_replica_lag_entitlements_2026_04_09`
- `medium_queue_autoscaling_regression_2026_03_18`
- `medium_az_egress_policy_regression_2026_02_27`

### Hard

- `hard_gateway_reconnect_storm_2026_05_03`
- `hard_feature_flag_cache_stampede_2026_04_14`
- `hard_service_mesh_timeout_chain_2026_03_07`
- `hard_cross_region_queue_replay_storm_2026_01_18`

Each incident directory contains:

- `metadata.json`
- `deployments.json`
- `commits.json`
- `metrics.json`
- `logs.json`
- `timeline.json`
- `expected_rca.json`

There are 21 runbooks under `data/runbooks/`.

## Evaluation Boundary

`expected_rca.json` is evaluation-only. It must not be ingested into the runtime graph.

It may be used by offline evaluation scripts to score:

- RCA correctness
- evidence recall
- traversal accuracy
- citation quality
- confidence calibration

The current dataset has only high-confidence ground truth labels, so low/medium confidence behavior must be tested through intentionally incomplete query results or lightweight future fixture additions.

## Architecture

### Stack

| Layer | Technology |
|---|---|
| Graph database | Neo4j 5.x |
| Local LLM | llama.cpp with a small quantized model suitable for M1 |
| Embeddings | Lightweight local sentence-transformer model |
| Backend | FastAPI |
| UI | Chainlit |
| Containerization | Docker Compose |

### Query Flow

```text
User question
  -> entity extraction
  -> graph traversal
  -> neighborhood expansion
  -> evidence aggregation
  -> vector retrieval for enrichment
  -> context assembly
  -> llama.cpp generation
  -> evidence-backed RCA with citations
```

## UI Contract

The Chainlit UI should expose the investigation in four visible steps:

1. Entities extracted
2. Graph traversal and evidence neighborhood
3. Hypotheses supported or ruled out
4. RCA with citations and confidence rationale

## Weekend Scope

Prioritize the work that demonstrates the GraphRAG thesis:

- deterministic ingestion of all incident files except `expected_rca.json`
- canonical IDs and idempotent graph construction
- evidence-oriented graph traversal
- hypothesis support/rule-out display
- citation-backed RCA generation
- minimal FastAPI and Chainlit surfaces
- offline evaluation against benchmark files

Defer anything that does not improve traversal accuracy, citation quality, hypothesis transparency, or RCA correctness.

## Out of Scope

- real-time log ingestion
- external observability integrations
- cloud LLM calls
- multi-tenant authentication
- ReAct-style dynamic tool loops
- full production SLOs or deployment hardening
- manual ingestion of ground-truth RCA answers

## Guiding Constraint

If a feature improves polish but does not improve traversal accuracy, evidence citation quality, hypothesis elimination transparency, or RCA correctness, it is lower priority than graph and retrieval correctness.
