# Prompting

This package is responsible for turning resolved retrieval outputs into
LLM-ready prompt inputs and grounded RCA drafts.

Scope:

- context assembly from retrieval evidence bundles
- prompt templates for RCA generation
- llama.cpp request shaping
- output parsing and response normalization

Suggested flow:

1. Accept a resolved `EvidenceBundle` and retrieval summary.
2. Build a compact structured context with citation-ready node IDs.
3. Render a deterministic RCA prompt template.
4. Send the prompt to the local LLM client.
5. Parse the model output into a structured RCA response shape.

This scaffold intentionally contains no implementation logic yet.
