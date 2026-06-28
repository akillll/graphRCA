# Chainlit UI

This package is responsible for exposing GraphRCA through a Chainlit chat UI.

Scope:

- accept a user question in chat
- call the backend `POST /investigate` endpoint
- render the investigation in clear step-by-step form
- display grounded RCA output, hypotheses, and citations
- handle API and empty-result errors cleanly

Constraint:

- the UI talks only to `/investigate`
- it does not query Neo4j directly
- it does not call retrieval or prompting modules directly
- it does not depend on graph stats or incident subgraph endpoints

Suggested flow:

1. Accept a natural-language question in Chainlit.
2. Send the question to the backend API.
3. Render the returned investigation summary in ordered steps.
4. Show the final RCA answer with citations and recommended actions.

This scaffold intentionally contains no implementation logic yet.
