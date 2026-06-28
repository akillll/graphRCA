# GraphRCA

Local GraphRAG-powered incident investigation system for evidence-backed root cause analysis.

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
