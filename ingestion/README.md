# Ingestion

This package is responsible for turning dataset files into canonical graph nodes and edges.

Scope:

- deterministic parsing of incident JSON and runbook markdown
- LLM-assisted semantic enrichment
- graph load orchestration
- ingestion provenance and validation

Suggested flow:

1. Parse deterministic sources into canonical node and edge payloads.
2. Run optional LLM-assisted enrichment on top of deterministic outputs.
3. Validate IDs, edge endpoints, and provenance.
4. Upsert into Neo4j.

This scaffold intentionally contains no implementation logic yet.
