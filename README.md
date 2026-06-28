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
- FastAPI API and Chainlit UI over a local `llama.cpp` server

## Current Limits

- This project currently relies on graph-first retrieval plus lightweight semantic incident resolution, not full embedding-backed semantic search across all evidence.
- Richer semantic retrieval is a future-scope improvement. During development, the target machine was a MacBook Air M1 running a local 1B-parameter model via `llama.cpp`, so the implementation favored deterministic graph retrieval and compact local reasoning over heavier retrieval infrastructure.

## Prerequisites

- Python virtual environment
- Neo4j running locally
- `llama.cpp` built locally
- A local GGUF instruct model

## Environment

Add these values to `.env`:

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

- Incident Resolution
- Evidence Summary
- Hypothesis Evaluation
- Root Cause Analysis

## Sample Questions

These are good benchmark-style questions to try from the UI or API:

- Why did catalog-api latency spike on April 21?
- Why were newly purchased premium features denied on April 9 even though checkout was still succeeding?
- What caused image processing backlog and worker restarts on May 22?
- Why were notification delays limited to only some tenants on March 18?
- What caused the distributed timeout chain in checkout on March 7?

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
