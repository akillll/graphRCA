# GraphRCA

Local GraphRAG-powered incident investigation system for evidence-backed root cause analysis.

This repository is intentionally built as a benchmark-first assessment system, not a production incident platform. It uses a fixed synthetic incident dataset to demonstrate local GraphRAG, graph-centered retrieval, hypothesis evaluation, and evidence-backed RCA generation with `llama.cpp`.

## What It Is

- A local GraphRAG prototype for incident RCA
- A benchmark-driven system built around 12 synthetic incident cases
- An assessment submission showing graph ingestion, retrieval, local inference, and investigation UX

## What It Is Not

- Not a production-ready observability product
- Not connected to live telemetry sources
- Not yet a fully general evaluation or vector-retrieval platform

## Current Capabilities

- Deterministic ingestion of benchmark incidents into Neo4j, excluding `expected_rca.json`
- Incident resolution using exact plus semantic query matching
- Incident-centered graph traversal and evidence assembly
- Hypothesis support/rule-out analysis with deterministic fallback scoring
- FastAPI API and Chainlit UI over a local `llama.cpp` server using `Llama-3.2-1B-Instruct-Q4_K_M.gguf`

## Current Limits

- This project currently relies on graph-first retrieval plus lightweight semantic incident resolution, not full embedding-backed semantic search across all evidence.
- Richer semantic retrieval is a future-scope improvement. During development, the target machine was a MacBook Air M1 running a local 1B-parameter model via `llama.cpp`, so the implementation favored deterministic graph retrieval and compact local reasoning over heavier retrieval infrastructure.
- This was built in a tight 3-day window, so the priority was graph correctness, evidence traceability, and hypothesis transparency over deeper production hardening, broader regression coverage, or infrastructure polish.

## Related Documents

- [PRD.md](/Users/aivantatechnologies/Desktop/Code/graphRCA/PRD.md)
- [questions.txt](/Users/aivantatechnologies/Desktop/Code/graphRCA/questions.txt)

## Prerequisites

- Python virtual environment
- Neo4j running locally
- `llama.cpp` built locally
- A local GGUF instruct model

## Environment

Start from the example file:

```bash
cp .env.example .env
```

Then update the values in `.env` for your local Neo4j and `llama-server` setup:

```env
APP_NAME=GraphRCA API
APP_ENV=development

NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=graph

LLAMA_CPP_ENDPOINT_URL=http://127.0.0.1:8080/v1/chat/completions
LLAMA_CPP_TIMEOUT_SECONDS=120

RETRIEVAL_DEBUG_ENABLED=true

UI_BACKEND_BASE_URL=http://127.0.0.1:8000
UI_INVESTIGATE_ENDPOINT=/investigate
UI_REQUEST_TIMEOUT_SECONDS=120
```

## Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install chainlit
```

## Run The Application

Use three terminals.

### Terminal 1: Start llama.cpp server

```bash
source venv/bin/activate
./build/bin/llama-server \
  -m "/Users/aivantatechnologies/Desktop/Code/graphRCA/llm model/Llama-3.2-1B-Instruct-Q4_K_M.gguf" \
  -c 16384 \
  -ngl 99 \
  --host 127.0.0.1 \
  --port 8080 \
  --temp 0.1
```

Notes:

- `llama-cli` is not enough for the app. The API needs `llama-server`.
- If your machine cannot handle `-c 16384`, reduce it, but smaller values may fail on larger prompts.

### Terminal 2: Start FastAPI backend

```bash
source venv/bin/activate
uvicorn api.app:app --reload --port 8000
```

### Terminal 3: Start Chainlit UI

```bash
source venv/bin/activate
chainlit run ui/app.py -w --port 8001
```

Open:

```text
http://localhost:8001
```

## Docker Compose

If `llama.cpp` is already set up on your machine and `llama-server` is running separately, you can use Docker Compose for the app layer. This setup assumes Neo4j is already running somewhere you can reach it, and Compose will run ingestion first before starting the API and Chainlit.

```bash
docker compose up --build
```

If your Docker install exposes the classic Compose binary instead, use:

```bash
docker-compose up --build
```

This flow does three things:

- runs deterministic ingestion into your existing Neo4j instance
- FastAPI on `http://localhost:8000`
- Chainlit on `http://localhost:8001`

Default Docker settings:

- Neo4j user: `neo4j`
- Neo4j password: `graphRCApassword`
- Neo4j URI: `bolt://host.docker.internal:7687`
- Llama endpoint: `http://host.docker.internal:8080/v1/chat/completions`

This Compose file does not start Neo4j itself. The assumption is that Neo4j is already running, whether through Docker Desktop, a local CLI process, or another local setup.

If your local `llama-server` is reachable through a different host alias under Colima, override it when starting Compose:

```bash
LLAMA_BASE_URL=http://host.lima.internal:8080/v1/chat/completions docker compose up --build
```

You can also override the Neo4j password the same way:

```bash
NEO4J_PASSWORD=your_password docker compose up --build
```

If Neo4j is also exposed through a different host alias under Colima, override that too:

```bash
NEO4J_URI=bolt://host.lima.internal:7687 docker compose up --build
```

## Basic API Checks

Health:

```bash
curl http://127.0.0.1:8000/health
```

Graph stats:

```bash
curl http://127.0.0.1:8000/graph/stats
```

Investigate an easy incident:

```bash
curl -X POST http://127.0.0.1:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why did catalog-api latency spike on April 21?"
  }'
```

Investigate a hard incident:

```bash
curl -X POST http://127.0.0.1:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What caused the distributed timeout chain in checkout on March 7?"
  }'
```

## Basic UI Check

After Chainlit starts, ask:

```text
Why did catalog-api latency spike on April 21?
```

The UI should render:

- RCA as the main visible response
- Question Resolution in a collapsible section
- Evidence Neighborhood in a collapsible section
- Hypothesis Evaluation in a collapsible section

## Sample Questions

These are good benchmark-style questions to try from the UI or API:

- Why did catalog-api latency spike on April 21?
- Why were newly purchased premium features denied on April 9 even though checkout was still succeeding?
- What caused image processing backlog and worker restarts on May 22?
- Why were notification delays limited to only some tenants on March 18?
- What caused the distributed timeout chain in checkout on March 7?

For a broader curated test set, see [questions.txt](/Users/aivantatechnologies/Desktop/Code/graphRCA/questions.txt).

## Future Scope

- Add lightweight conversation context so follow-up questions can stay grounded in the same investigation instead of starting from scratch every time.
- Add some practical request limits so the API and UI stay stable if the system gets heavier use.
- Add basic auth and access controls before treating this as something more than a local benchmark project.
- Add better logging and request tracing so investigations are easier to replay and debug later.
- Tighten input handling and prompt boundaries so the system is more resilient to messy or adversarial inputs.
- Improve secrets and config handling so local setup is safer and logs do not leak sensitive values.
- Add a more production-aware deployment layer with better defaults around transport security and trusted access.
- Add a few guardrails around timeouts, concurrency, and resource usage so Neo4j and the local model fail more predictably under load.
- Add richer semantic retrieval, reranking, and evaluation once the graph-first baseline feels stable enough.
- Try a stronger local model for better RCA quality if hardware allows, since the current setup was tuned around lightweight local inference on constrained hardware.

## Troubleshooting

If `/investigate` returns `model_unavailable`:

- confirm `llama-server` is running
- confirm `LLAMA_CPP_ENDPOINT_URL=http://127.0.0.1:8080/v1/chat/completions`

If `/investigate` returns context-size errors:

- increase `llama-server` context size with `-c 16384`

If Chainlit cannot import local modules:

- run it from the repo root:

```bash
chainlit run ui/app.py -w --port 8001
```

If the backend is up but Chainlit cannot connect:

- confirm `.env` includes:

```env
UI_BACKEND_BASE_URL=http://127.0.0.1:8000
```
