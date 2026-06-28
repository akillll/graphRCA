# API

This package is responsible for exposing GraphRCA functionality over HTTP.

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

This scaffold intentionally contains no implementation logic yet.
