# GRAPH_SPEC.md - GraphRCA Graph Layer Specification

## Purpose

GraphRCA uses GraphRAG because incident investigation is a relationship problem. Traditional vector RAG can retrieve relevant chunks, but it does not preserve the operational structure that matters for RCA: deployment timing, changed files, metric movement, log symptoms, service involvement, runbook relevance, and hypothesis elimination.

The graph is the primary retrieval system. It stores operational evidence and typed relationships so the system can traverse from an incident to the evidence neighborhood before asking the LLM to write an answer.

The graph represents **evidence relationships**, not assumed truth. During ingestion, the system should not assert that a deployment or commit definitively caused an outage unless that assertion exists as explicit source evidence. Most relationships are weaker and more useful when modeled as evidence:

- a deployment occurred before an incident
- a commit changed a component
- a metric was observed during an incident window
- a log event matched a pattern
- a runbook matches a symptom
- a piece of evidence supports or rules out a hypothesis

Causal conclusions are produced at query time by synthesizing graph evidence, not by baking final RCA answers into ingestion.

## Node Types

All nodes require:

- `id`: canonical deterministic ID
- `source`: source file or source category
- `created_by`: `rule` or `llm`

LLM-created nodes also require:

- `model`: model identifier when available
- `confidence`: extraction confidence from 0.0 to 1.0 when available

### Incident

Represents one benchmark incident.

Required fields:

- `id`
- `title`
- `difficulty`
- `service`
- `severity`
- `start_time`
- `end_time`

Optional fields:

- `summary`
- `tags`

Canonical ID:

- `incident:{metadata.id}`

Example:

- `incident:easy_cache_warmup_regression_2026_04_21`

### Service

Represents a service or operational component mentioned by incident data.

Required fields:

- `id`
- `name`

Optional fields:

- `type`
- `environment`
- `tier`
- `aliases`

Canonical ID:

- `service:{service_name}`

Example:

- `service:catalog-api`

### Deployment

Represents a deployment, rollback, or maintenance operation.

Required fields:

- `id`
- `deployment_id`
- `timestamp`
- `service`
- `environment`
- `version`
- `strategy`
- `status`

Optional fields:

- `initiated_by`
- `commit_ids`

Canonical ID:

- `deployment:{deployment_id}`

Example:

- `deployment:catalog-prod-6107`

### Commit

Represents a commit associated with a deployment window.

Required fields:

- `id`
- `commit_id`
- `timestamp`
- `message`
- `files_changed`

Optional fields:

- `author`

Canonical ID:

- `commit:{commit_id}`

Example:

- `commit:55b191e`

### Metric

Represents the named metric identity, independent of time-series values.

Required fields:

- `id`
- `name`

Optional fields:

- `service`
- `unit`
- `component`

Canonical ID:

- `metric:{metric_name}`

Example:

- `metric:redis_cache_a.hit_rate_percent`

### MetricSeries

Represents one incident-scoped observed time series for a metric.

Required fields:

- `id`
- `metric`
- `incident_id`
- `window_start`
- `window_end`
- `resolution`
- `points`
- `unit`

Optional fields:

- `baseline_value`
- `min_value`
- `max_value`
- `first_anomalous_at`
- `direction`
- `service`

Canonical ID:

- `metric_series:{incident_id}:{metric_name}`

Example:

- `metric_series:easy_cache_warmup_regression_2026_04_21:redis_cache_a.hit_rate_percent`

### LogEvent

Represents a raw log event.

Required fields:

- `id`
- `timestamp`
- `level`
- `service`
- `component`
- `message`

Optional fields:

- `trace_id`

Canonical ID:

- `log_event:{incident_id}:{timestamp}:{trace_id_or_sequence}`

Example:

- `log_event:easy_cache_warmup_regression_2026_04_21:2026-04-21T13:17:35Z:cat-72b1`

### LogPattern

Represents a semantic grouping of related log events.

Required fields:

- `id`
- `incident_id`
- `pattern`
- `level`
- `first_seen`
- `count`

Optional fields:

- `service`
- `component`
- `representative_message`
- `keywords`

Canonical ID:

- `log_pattern:{incident_id}:{slugified_pattern}`

Example:

- `log_pattern:easy_cache_warmup_regression_2026_04_21:redis_miss`

### Runbook

Represents one runbook document.

Required fields:

- `id`
- `filename`
- `title`
- `content`

Optional fields:

- `symptoms`
- `diagnostics`
- `common_causes`
- `recommended_actions`

Canonical ID:

- `runbook:{filename}`

Example:

- `runbook:cache_degradation.md`

### Hypothesis

Represents a candidate explanation considered for an incident.

Required fields:

- `id`
- `incident_id`
- `text`
- `status`

Optional fields:

- `rank`
- `rationale`

Allowed status values:

- `candidate`
- `supported`
- `ruled_out`
- `confirmed`

Canonical ID:

- `hypothesis:{incident_id}:{slugified_hypothesis_text}`

Example:

- `hypothesis:easy_cache_warmup_regression_2026_04_21:redis_outage`

### Configuration

Represents operational context, configuration, policy, feature flag, or maintenance context.

Required fields:

- `id`
- `incident_id`
- `text`
- `kind`

Optional fields:

- `service`
- `timestamp`
- `source_field`

Canonical ID:

- `config:{incident_id}:{slugified_text_or_sequence}`

Example:

- `config:hard_service_mesh_timeout_chain_2026_03_07:zone_aware_routing_policy_rollout`

### Action

Represents a recommended or observed remediation action.

Required fields:

- `id`
- `text`
- `kind`

Optional fields:

- `incident_id`
- `runbook_id`
- `timestamp`
- `actor`

Allowed kind values:

- `observed`
- `recommended`

Canonical ID:

- `action:{source_id}:{slugified_action_text}`

Example:

- `action:runbook:cache_degradation.md:roll_back_recent_cache_policy_changes`

### TimelineEvent

Represents a structured event from `timeline.json`.

Required fields:

- `id`
- `incident_id`
- `timestamp`
- `actor`
- `event`

Optional fields:

- `event_type`
- `linked_node_id`
- `references`

Canonical ID:

- `timeline_event:{incident_id}:{timestamp}:{sequence}`

Example:

- `timeline_event:easy_cache_warmup_regression_2026_04_21:2026-04-21T13:24:00Z:4`

## Edge Types

All edges require:

- `source`: source file or source category
- `created_by`: `rule` or `llm`
- `deterministic`: boolean

LLM-created edges also require:

- `model`
- `confidence`
- `rationale`

### OBSERVED_IN

Connects evidence to the incident where it was observed.

Examples:

- `MetricSeries -> Incident`
- `LogEvent -> Incident`
- `LogPattern -> Incident`
- `TimelineEvent -> Incident`
- `Configuration -> Incident`

Deterministic when created directly from incident files.

### OCCURRED_AFTER

Connects temporally ordered nodes.

Examples:

- `Incident -> Deployment`
- `LogEvent -> Deployment`
- `TimelineEvent -> TimelineEvent`

Deterministic when timestamps are present. This edge means temporal ordering only, not causality.

### OBSERVED_ON

Connects evidence to a service.

Examples:

- `Deployment -> Service`
- `MetricSeries -> Service`
- `LogEvent -> Service`
- `Incident -> Service`

Deterministic when a `service` field exists.

### DEPENDS_ON

Connects service topology.

Example:

- `Service -> Service`

Deterministic only when supplied by `services.json` or another explicit topology file. LLM-inferred service dependencies are allowed only as inferred edges and should not be used as hard proof.

### CHANGED

Connects commits or deployments to changed configuration or services.

Examples:

- `Commit -> Configuration`
- `Commit -> Service`
- `Deployment -> Service`

Rule-generated when commit file paths or deployment service fields identify the target. LLM-assisted when deriving a configuration concept from commit messages or files.

### INCLUDED_IN

Connects commits to deployments when the incident dataset implies that recent commits are associated with a deployment window.

Example:

- `Commit -> Deployment`

This is deterministic only if the dataset explicitly maps commits to a deployment. In the current dataset, it should be treated as rule-generated association by incident window, not exact release membership, unless implementation adds a stricter mapping.

### MATCHES

Connects semantically similar or pattern-matched nodes.

Examples:

- `LogEvent -> LogPattern`
- `Incident -> Runbook`
- `LogPattern -> Runbook`
- `Hypothesis -> Runbook`

Rule-generated for explicit `metadata.relevant_runbooks`. LLM-assisted for semantic log grouping and runbook matching.

### SUPPORTS

Connects evidence to a hypothesis it supports.

Examples:

- `MetricSeries -> Hypothesis`
- `LogPattern -> Hypothesis`
- `Deployment -> Hypothesis`
- `Commit -> Hypothesis`
- `Configuration -> Hypothesis`

LLM-assisted or rule-generated from transparent heuristics. This edge does not mean the hypothesis is confirmed by itself.

### RULES_OUT

Connects evidence to a hypothesis it weakens or eliminates.

Examples:

- `MetricSeries -> Hypothesis`
- `LogPattern -> Hypothesis`
- `Configuration -> Hypothesis`

LLM-assisted or rule-generated from transparent heuristics. Must include rationale.

### REFERENCES

Connects nodes to cited source material.

Examples:

- `Runbook -> Action`
- `TimelineEvent -> Deployment`
- `TimelineEvent -> MetricSeries`

Rule-generated when an explicit file or field reference exists. LLM-assisted when mapping prose to a known graph node.

### RECOMMENDS

Connects runbooks or generated RCA actions to remediation actions.

Examples:

- `Runbook -> Action`
- `Hypothesis -> Action`

Rule-generated from structured runbook headings when possible. LLM-assisted for extracting action text from prose.

## Canonical IDs

Canonical IDs make graph construction deterministic and idempotent.

| Node Type | Format |
|---|---|
| Incident | `incident:{metadata.id}` |
| Service | `service:{service_name}` |
| Deployment | `deployment:{deployment_id}` |
| Commit | `commit:{commit_id}` |
| Metric | `metric:{metric_name}` |
| MetricSeries | `metric_series:{incident_id}:{metric_name}` |
| LogEvent | `log_event:{incident_id}:{timestamp}:{trace_id_or_sequence}` |
| LogPattern | `log_pattern:{incident_id}:{slugified_pattern}` |
| Runbook | `runbook:{filename}` |
| Hypothesis | `hypothesis:{incident_id}:{slugified_hypothesis_text}` |
| Configuration | `config:{incident_id}:{slugified_text_or_sequence}` |
| Action | `action:{source_id}:{slugified_action_text}` |
| TimelineEvent | `timeline_event:{incident_id}:{timestamp}:{sequence}` |

Slug rules:

- lowercase
- trim whitespace
- replace non-alphanumeric runs with `_`
- strip leading and trailing `_`
- keep IDs stable across reruns

Sequence rules:

- For `LogEvent`, use `trace_id` when present. If `trace_id` is missing, use the zero-based array index from `logs.json` as `seq_{index}`.
- For `TimelineEvent`, use the zero-based array index from `timeline.json`.
- Sequence values are based on source file order and must not be re-sorted before ID construction.
- Timestamp ordering may be used for `OCCURRED_AFTER` edges after IDs are built.

## Graph Construction Pipeline

### Deterministic Extraction

Structured files create factual nodes and factual edges.

#### `metadata.json`

Nodes:

- `Incident`
- primary `Service`
- `Hypothesis` nodes from `primary_hypotheses` with status `candidate`
- `Configuration` nodes from `operational_context`, when present
- `Service` nodes from `affected_services`, when present
- `Service` nodes and aliases from `services.json`, when present

Edges:

- `Incident -> Service` via `OBSERVED_ON`
- `Hypothesis -> Incident` via `OBSERVED_IN`
- `Configuration -> Incident` via `OBSERVED_IN`
- `Incident -> Runbook` via `MATCHES` for explicit `relevant_runbooks`
- `Incident -> Service` via `OBSERVED_ON` for `affected_services`
- `Service -> Service` via `DEPENDS_ON` from `services.json.dependencies`, when present

Do not derive service-to-service `DEPENDS_ON` from `affected_services`; the array indicates involvement, not topology.

If `metadata.operational_context` entries are strings, create `Configuration` nodes with:

- `kind: "operational_context"`
- `source_field: "operational_context"`
- `text` equal to the string value

If an entry is an object in a future fixture, preserve explicit `kind`, `service`, and `timestamp` when present.

#### `deployments.json`

Nodes:

- `Deployment`
- `Service`

Edges:

- `Deployment -> Incident` via `OBSERVED_IN`
- `Deployment -> Service` via `OBSERVED_ON`
- `Incident -> Deployment` via `OCCURRED_AFTER` when deployment timestamp precedes incident start or occurs during the incident window
- `Commit -> Deployment` via `INCLUDED_IN` for each explicit `commit_ids` entry

Rollback or maintenance status should be stored as properties, not causal truth.

#### `commits.json`

Nodes:

- `Commit`

Edges:

- `Commit -> Incident` via `OBSERVED_IN`
- `Commit -> Deployment` via `INCLUDED_IN` when a deployment explicitly lists the commit ID
- `Commit -> Service` via `CHANGED` when file paths or commit messages clearly identify a service

If `deployments.json.commit_ids` is absent, do not create deterministic `INCLUDED_IN` edges. Use an implementation-local association only for retrieval ranking and label it as non-exact.

#### `metrics.json`

Nodes:

- `Metric`
- `MetricSeries`

Edges:

- `MetricSeries -> Metric` via `REFERENCES`
- `MetricSeries -> Incident` via `OBSERVED_IN`
- `MetricSeries -> Service` via `OBSERVED_ON` from the explicit `service` field

Implementation may compute optional summary properties such as baseline, min, max, direction, and first anomaly time, but raw points should remain available for citation.

Deterministic metric summary rules:

- `baseline_value`: median of points with timestamps before `metadata.start_time`; if no pre-incident points exist, use the first point.
- `min_value`: minimum value across all points.
- `max_value`: maximum value across all points.
- `observed_value`: the most extreme value during `[metadata.start_time, metadata.end_time]`; choose `max_value` when direction is `up`, `min_value` when direction is `down`.
- `direction`: compare incident-window median to `baseline_value`; use `up` if higher, `down` if lower, `flat` if equal.
- `first_anomalous_at`: first incident-window timestamp whose value differs from `baseline_value` by at least 20 percent. For baseline zero, use the first non-zero incident-window point.

These summaries are helper properties for ranking and explanation. Citations should still reference raw point values.

#### `logs.json`

Nodes:

- `LogEvent`
- `Service`

Edges:

- `LogEvent -> Incident` via `OBSERVED_IN`
- `LogEvent -> Service` via `OBSERVED_ON`
- `LogEvent -> TimelineEvent` via `REFERENCES` only when timestamp/message matching is reliable

#### `timeline.json`

Nodes:

- `TimelineEvent`

Edges:

- `TimelineEvent -> Incident` via `OBSERVED_IN`
- `TimelineEvent -> TimelineEvent` via `OCCURRED_AFTER` for adjacent timestamp ordering
- `TimelineEvent -> Deployment`, `MetricSeries`, `LogPattern`, or `Hypothesis` via `REFERENCES` from explicit `references`, when present

Do not create deterministic timeline reference edges from prose matching alone. Prose matching may produce LLM-assisted `REFERENCES` edges with confidence and rationale.

#### `runbooks/*.md`

Nodes:

- `Runbook`
- optionally `Action`

Edges:

- `Runbook -> Action` via `RECOMMENDS` for extracted recommended actions

Runbooks are runtime knowledge, not evaluation labels.

#### `expected_rca.json`

Nodes:

- none in the runtime graph

Edges:

- none in the runtime graph

This file is evaluation-only.

### LLM-Assisted Extraction

LLM-assisted extraction is allowed for semantic structure that is not directly encoded:

- log pattern grouping from `logs.json`
- hypothesis support or rule-out relationships
- runbook section extraction when headings vary
- semantic runbook matching when `metadata.relevant_runbooks` is insufficient
- mapping timeline prose to known graph nodes

LLM-assisted output must be structured JSON and must include:

- node or edge type
- source node ID
- target node ID when applicable
- confidence
- rationale
- source file

## Graph Traversal

Query execution should follow this flow:

```text
Question
  -> entity extraction
  -> graph traversal
  -> neighborhood expansion
  -> evidence aggregation
  -> vector retrieval
  -> context assembly
  -> llama.cpp generation
  -> evidence-backed RCA
```

### 1. Entity Extraction

Extract candidate:

- incident IDs
- service names
- metric names
- symptoms
- dates or time ranges
- hypothesis terms

Use exact matching first. Use the LLM as a fallback for natural-language questions.

### 2. Graph Traversal

Starting from matched incidents or services, retrieve:

- incident node
- observed services
- deployments in or before the incident window
- commits associated with the incident window
- metric series observed during the incident
- log events and log patterns
- candidate hypotheses
- operational context
- matched runbooks
- timeline events

### 3. Neighborhood Expansion

Expand one to two hops around high-signal evidence:

- `SUPPORTS`
- `RULES_OUT`
- `MATCHES`
- `REFERENCES`
- `OCCURRED_AFTER`

Avoid unbounded traversal.

### 4. Evidence Aggregation

Group evidence by source type:

- deployments
- commits
- metrics
- logs
- operational context
- runbooks
- affected services
- timeline events

The generator should receive compact structured evidence, not raw full files.

### 5. Vector Retrieval

Use vector search for enrichment after graph traversal:

- retrieve relevant runbook passages
- retrieve similar log patterns
- retrieve nearby action language

Vector retrieval must not override graph evidence. It can add context, not invent the causal chain.

### 6. Context Assembly

The prompt to llama.cpp should include:

- user question
- extracted entities
- traversed node IDs
- traversed edge IDs/types
- evidence grouped by source
- supported hypotheses
- ruled-out hypotheses
- citation IDs
- confidence rules

### 7. RCA Generation

The final answer should include:

- concise root cause statement
- evidence trail with node IDs
- hypotheses considered
- hypotheses ruled out and why
- confidence and confidence rationale
- recommended actions when supported by runbooks or evidence

## Retrieval Philosophy

The graph is the primary retrieval mechanism because the core question is relational: what changed, when did symptoms appear, which services were involved, and what evidence supports or rules out each hypothesis.

Vector search is useful for semantic enrichment:

- finding relevant runbook passages
- grouping log messages
- matching symptoms to operational guidance

Vector search alone is insufficient because it retrieves text chunks without preserving evidence provenance, time ordering, or typed operational relationships.

## Evaluation

Runtime graph and evaluation data must remain separate.

### Runtime Graph

The runtime graph may ingest:

- `metadata.json`
- `deployments.json`
- `commits.json`
- `metrics.json`
- `logs.json`
- `timeline.json`
- `runbooks/*.md`
- `services.json` topology files

### Evaluation Data

`expected_rca.json` must never be ingested into the runtime graph.

It is used only after the system produces an answer.

### Metrics

**RCA correctness**

Compare generated RCA against `expected_rca.root_cause`.

**Evidence recall**

Check whether answer citations cover the source categories in `expected_rca.evidence_sources`.

**Traversal accuracy**

Compare traversed evidence categories and investigation steps against `expected_rca.expected_investigation_path`. Because the current path is natural language, the first implementation should score this at the source-category/step-label level rather than exact node-path equality.

**Citation quality**

Validate that cited node IDs exist in the runtime graph and that citation text accurately reflects node properties.

**Hypothesis handling**

Check whether the answer names plausible alternatives from `metadata.primary_hypotheses` and gives evidence-backed support or rule-out rationale.

**Confidence calibration**

Check whether the answer avoids high confidence when key source categories are missing from traversal. The current dataset has only high-confidence expected labels, so missing-evidence simulations are needed for low/medium behavior.

## Dataset Contract

### Current Dataset Shape

The repository contains 12 incidents:

| Tier | Incidents |
|---|---|
| Easy | `db_pool_exhaustion`, `cache_warmup_regression`, `webhook_retry_amplification`, `redis_tls_misconfig` |
| Medium | `media_worker_memory_leak`, `replica_lag_entitlements`, `queue_autoscaling_regression`, `az_egress_policy_regression` |
| Hard | `gateway_reconnect_storm`, `feature_flag_cache_stampede`, `service_mesh_timeout_chain`, `cross_region_queue_replay_storm` |

Every incident directory contains:

- `metadata.json`
- `deployments.json`
- `commits.json`
- `metrics.json`
- `logs.json`
- `timeline.json`
- `expected_rca.json`

Hard incident directories also contain:

- `services.json`

### File Mapping

| File | Runtime Nodes | Runtime Edges | Method |
|---|---|---|---|
| `metadata.json` | Incident, Service, Hypothesis, Configuration | OBSERVED_ON, OBSERVED_IN, MATCHES | deterministic |
| `deployments.json` | Deployment, Service | OBSERVED_IN, OBSERVED_ON, OCCURRED_AFTER | deterministic |
| `commits.json` | Commit | OBSERVED_IN, INCLUDED_IN, CHANGED | deterministic with conservative heuristics |
| `metrics.json` | Metric, MetricSeries | REFERENCES, OBSERVED_IN, OBSERVED_ON | deterministic with derived summaries |
| `logs.json` | LogEvent, Service | OBSERVED_IN, OBSERVED_ON | deterministic |
| `timeline.json` | TimelineEvent | OBSERVED_IN, OCCURRED_AFTER, REFERENCES | deterministic plus optional matching |
| `runbooks/*.md` | Runbook, Action | RECOMMENDS, MATCHES | deterministic headings plus LLM-assisted extraction |
| `services.json` | Service | DEPENDS_ON | deterministic |
| `expected_rca.json` | none | none | evaluation-only |

### Minimal Dataset Additions Status

Do not redesign the dataset. Add only low-risk files or fields that materially improve graph traversal.

#### 1. `services.json` per hard incident

Status: added for hard incidents.

Purpose: encode service topology for distributed reasoning.

Recommended minimal format:

```json
{
  "services": [
    {"name": "checkout-orchestrator", "type": "api"},
    {"name": "pricing-api", "type": "api"},
    {"name": "inventory-api", "type": "api"}
  ],
  "dependencies": [
    {"from": "checkout-orchestrator", "to": "pricing-api", "relationship": "calls"},
    {"from": "checkout-orchestrator", "to": "inventory-api", "relationship": "calls"}
  ]
}
```

Graph mapping:

- create `Service` nodes
- create deterministic `DEPENDS_ON` edges

This is the highest-value addition because hard incidents require multiple affected services, but current `affected_services` arrays do not encode dependency direction.

#### 2. Deployment-to-commit mapping

Status: added as `commit_ids` on deployment records.

Purpose: avoid pretending every nearby commit was included in every deployment.

Recommended minimal field in `deployments.json`:

```json
"commit_ids": ["55b191e", "d53c9e4"]
```

Graph mapping:

- create deterministic `Commit -> Deployment` `INCLUDED_IN` edges

If omitted, implementations must label commit/deployment edges as incident-window associations.

#### 3. Metric service mapping

Status: added as `service` on every metric series.

Purpose: avoid brittle service inference from metric names.

Recommended minimal field in each metric series:

```json
"service": "redis-cache-a"
```

Graph mapping:

- create deterministic `MetricSeries -> Service` `OBSERVED_ON` edges

#### 4. Optional timeline references

Status: not required for initial implementation.

Purpose: create exact timeline-to-evidence references without prose matching.

Recommended optional field on timeline events:

```json
"references": ["deployment:catalog-prod-6107"]
```

Graph mapping:

- create deterministic `TimelineEvent -> referenced node` `REFERENCES` edges

If omitted, only adjacent timeline ordering is deterministic.

#### 5. Keep `expected_investigation_path`, but add optional machine-readable hints

Purpose: improve traversal scoring without rewriting ground truth.

Recommended optional field:

```json
"expected_evidence_nodes": [
  "deployment:catalog-prod-6107",
  "commit:55b191e",
  "metric_series:easy_cache_warmup_regression_2026_04_21:redis_cache_a.hit_rate_percent"
]
```

Graph mapping:

- none. Evaluation-only.

This improves scoring but must remain outside runtime ingestion.

## Scope Controls

For the current local build:

- implement deterministic ingestion first
- use LLM-assisted extraction only where it visibly improves hypothesis support/rule-out or runbook/log matching
- avoid global ontology complexity
- avoid unbounded graph expansion
- avoid causal truth edges during ingestion
- make citations and traversal visible before adding polish
