# Retrieval

This package is responsible for resolving user questions into incident candidates,
traversing the graph, and assembling structured evidence bundles for downstream
prompting.

Scope:

- query entity extraction
- incident and service resolution
- Neo4j read access and Cypher queries
- incident-centered graph traversal
- evidence assembly for debugging and prompting

Suggested flow:

1. Extract deterministic entities from the question.
2. Resolve one or more incident candidates from the graph.
3. Traverse the incident-centered evidence neighborhood.
4. Assemble a compact, citation-ready evidence bundle.

