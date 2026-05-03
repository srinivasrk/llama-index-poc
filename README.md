# LlamaIndex + LangGraph + Graphiti RAG PoC (Gemini + Chroma + Neo4j + Next.js)

Local proof of concept for a hybrid RAG assistant grounded in two retrieval paths:

- **Backend**: FastAPI + LlamaIndex + LangGraph (async)
- **LLM/Embeddings**: Gemini
- **Vector store**: Chroma (persistent)
- **Knowledge graph**: Graphiti on Neo4j (temporal, bi-temporal edges)
- **Frontend**: Next.js with a live Cytoscape graph viz

The assistant answers from retrieved knowledge base chunks **and** Graphiti facts. If both are empty it refuses. Graphiti facts can ground answers vector search misses (especially across sessions), and edges that get superseded over time are kept and marked `invalid_at` rather than deleted — so the assistant can correctly answer *"what used to depend on Postgres?"*.

## Table of contents

- [What this project does](#what-this-project-does)
- [Current Features](#current-features)
- [Architecture at a glance](#architecture-at-a-glance)
- [Why LlamaIndex and Neo4j?](#why-llamaindex-and-neo4j)
  - [LlamaIndex + Chroma (vector RAG)](#llamaindex-chroma-vector-rag)
  - [Neo4j (via Graphiti)](#neo4j-via-graphiti)
  - [How they work together](#how-they-work-together)
- [Prerequisites](#prerequisites)
  - [Align Neo4j credentials](#align-neo4j-credentials)
- [Automated dev startup (Windows)](#automated-dev-startup-windows)
- [Quick start](#quick-start)
- [Backend `.env`](#backend-env)
- [Disabling Graphiti](#disabling-graphiti)
- [KB graph vs chat memory](#kb-graph-vs-chat-memory)
- [API Endpoints](#api-endpoints)
- [How Data Is Stored](#how-data-is-stored)
- [Resetting state (clean re-index)](#resetting-state-clean-re-index)
- [Try the temporal-update demo](#try-the-temporal-update-demo)
- [Notes](#notes)

## What this project does

This PoC demonstrates **time-aware RAG**:

- Builds a standard vector index (Chroma) for semantic chunk retrieval
- Builds a temporal knowledge graph (Graphiti + Neo4j) from the same docs and from chat turns
- Tracks fact evolution across document versions (for example April vs October runbooks)
- Preserves superseded relationships with `valid_at` / `invalid_at` instead of overwriting history
- Combines current + historical graph facts with vector context during answer generation

In practice, this means the assistant can answer both:

- **Current state questions**: "Who leads Commerce now?"
- **Historical state questions**: "Who used to lead Payments?" or "Has Checkout always used DynamoDB?"

## Current Features

- Upload `.md`, `.txt`, `.pdf` documents from the UI (`/upload`)
- Ingest/index documents into Chroma **and** push them into Graphiti as text episodes (`/ingest`)
- Query via chat with citations (`/chat`) — answers are grounded by both vector chunks and graph facts (when Graphiti is enabled)
- Optional **chat episodes**: when `ENABLE_CHAT_EPISODES=true`, chat turns are also ingested into Graphiti for cross-session grounding (separate group from the KB graph; see [KB graph vs chat memory](#kb-graph-vs-chat-memory))
- Guardrail-based refusal only triggers when **both** retrieval paths come up empty
- Debug endpoint to inspect vector index state (`/kb/debug`)
- Live knowledge-graph snapshot (`/graph/snapshot`) and Server-Sent Events stream (`/graph/stream`)
- Cytoscape canvas in the UI flashes new entities/edges as Graphiti extracts them, and renders invalidated facts as dotted-red edges

## Architecture at a glance

```text
┌────────────┐   /ingest    ┌────────────┐   add_episode   ┌────────────┐
│  Next.js   │─────────────▶│  FastAPI   │────────────────▶│  Graphiti  │
│  (chat +   │   /chat      │  + Lang-   │   add_episode   │  + Neo4j   │
│  graph UI) │◀────────────▶│  Graph     │◀────search──────│            │
│            │  /graph/*    │            │                 └────────────┘
│            │   (SSE)      │            │   retrieve      ┌────────────┐
└────────────┘              │            │────────────────▶│  Chroma    │
                            └────────────┘                 └────────────┘
```

## Why LlamaIndex and Neo4j?

This PoC deliberately uses **two retrieval paths**; they answer different shapes of “what does the knowledge base support?”

### LlamaIndex + Chroma (vector RAG)

Documents are split into chunks, embedded with Gemini, and stored in **Chroma**. At query time, LlamaIndex retrieves chunks whose **meaning** is closest to the question. That is strong for fuzzy, passage-style grounding (“find the paragraph that reads like this question”). It does **not** by itself give you a clean, navigable **graph** of entities and relationships, nor built-in **temporal** tracking of how a fact superseded an older one across document versions.

### Neo4j (via Graphiti)

**Neo4j is not LlamaIndex’s vector store in this repo.** It is the **graph database behind Graphiti**. Graphiti ingests text (from `/ingest`, and optionally from chat when `ENABLE_CHAT_EPISODES=true`), extracts entities and relationships, and stores them in Neo4j, including **time** on edges (`valid_at` / `invalid_at`) so you can represent current vs historical truth. The Next.js Cytoscape panel reads graph structure from this stack (`/graph/snapshot`, `/graph/stream`).

### How they work together

The LangGraph chat flow runs **vector chunk retrieval** and **Graphiti fact search** **in parallel**, then prompts the model with **both** chunk text and graph facts. The guardrail **refuses** only when **both** paths are empty—so structured graph facts can still ground an answer when semantic chunk retrieval comes up short (including some cross-session cases when chat episodes are enabled).

If you set **`ENABLE_GRAPHITI=false`**, you can run **LlamaIndex + Chroma only**; Neo4j is not required for that path.

## Prerequisites

- **Python** 3.10+
- **Node.js** 20+
- **Docker Desktop** (or Docker Engine) with **Compose v2**  
  - **Required** when `ENABLE_GRAPHITI=true` (default in `.env.example`): Neo4j is started from this repo’s `docker-compose.yml` on ports **7474** (browser) and **7687** (Bolt).  
  - **Optional** if you turn Graphiti off and only want vector RAG—see [Disabling Graphiti](#disabling-graphiti). You can use `start-dev.ps1 -SkipDocker` in that case.
- **Gemini API key** — set `GEMINI_API_KEY` in `backend/.env`

### Align Neo4j credentials

`docker-compose.yml` sets `NEO4J_AUTH` from the environment, defaulting to **`neo4j` / `password`** if unset. `backend/.env.example` uses **`NEO4J_PASSWORD=graphiti_dev_password`**, which must **match** the password Neo4j was **first** initialized with (the Docker volume keeps the original password).

Pick one consistent story, for example:

- **Match the example `.env`:** before the first `docker compose up`, set  
  `NEO4J_AUTH=neo4j/graphiti_dev_password`  
  (PowerShell: `$env:NEO4J_AUTH = "neo4j/graphiti_dev_password"`), **or** put that in a repo-root `.env` file that Compose reads, **or**
- **Match Compose’s default:** set `NEO4J_PASSWORD=password` in `backend/.env` (and use `neo4j` / `password` in Neo4j Browser).

## Automated dev startup (Windows)

After one-time setup (venv, `pip install`, `npm install`, copy/edit `.env` files—see [Quick start](#quick-start)), you can start **Docker Compose (Neo4j)**, the **backend**, and the **frontend** from the repo root:

| Entry point | What to run |
|-------------|-------------|
| Double-click | `start-dev.cmd` — runs PowerShell with `-ExecutionPolicy Bypass` |
| Terminal | `.\start-dev.ps1` |

Behavior:

1. Runs **`docker compose up -d`** in the repo root (Neo4j) unless Docker is unavailable.
2. Opens **two** new terminal windows: FastAPI with uvicorn on **port 8000**, and `npm run dev` for Next.js on **port 3000** (default).

Backend command resolution: prefers `backend\.venv\Scripts\python.exe -m uvicorn`, else `uv run uvicorn`, else `python -m uvicorn`.

**`-SkipDocker`** — `.\start-dev.ps1 -SkipDocker` skips Compose (useful for Graphiti-off / no Docker). The `.cmd` launcher does not pass flags; run the `.ps1` from a shell if you need `-SkipDocker`.

The scripts do **not** install dependencies or create `.env` files; do the manual steps below once per machine.

## Quick start

For a **one-shot dev session** after dependencies and `.env` exist, use [Automated dev startup (Windows)](#automated-dev-startup-windows). Otherwise:

```bash
# 1. Start Neo4j (skip if you don't want Graphiti — see "Disabling Graphiti" below)
docker compose up -d neo4j

# 2. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# edit backend/.env: set GEMINI_API_KEY; align NEO4J_PASSWORD with Neo4j (see "Align Neo4j credentials" above)
uv run uvicorn app.main:app --reload --port 8000

# 3. Frontend (new shell)
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`. Neo4j Browser: `http://localhost:7474` — user **`neo4j`**, password whatever you set via **`NEO4J_AUTH`** / first-time volume init (see [Align Neo4j credentials](#align-neo4j-credentials)).

## Backend `.env`

```dotenv
GEMINI_API_KEY=your_gemini_api_key
CHROMA_PERSIST_DIR=./storage/chroma
DOCS_DIR=./data
TOP_K=4
SIMILARITY_CUTOFF=0.5
RAG_FALLBACK_MESSAGE=I don't know based on the provided knowledge base.

# Graphiti / Neo4j
ENABLE_GRAPHITI=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=graphiti_dev_password
# KB episodes (from /ingest) — the only group rendered in the Cytoscape canvas.
GRAPHITI_GROUP_ID=llama-index-poc-kb
# Chat episodes live in their own group so they don't pollute the KB graph.
GRAPHITI_CHAT_GROUP_ID=llama-index-poc-chat
# Default OFF: chat turns are NOT pushed into Graphiti. Flip to true to enable
# cross-session chat memory; chat nodes still won't appear in the canvas
# because /graph/snapshot only queries GRAPHITI_GROUP_ID.
ENABLE_CHAT_EPISODES=false
```

## Disabling Graphiti

Set `ENABLE_GRAPHITI=false` in `backend/.env` and the app falls back to the **Chroma-only** RAG flow. You do **not** need Docker/Neo4j for that mode. Graphiti calls become no-ops and the graph panel in the UI shows an "offline" badge — nothing else breaks. If Graphiti is still `true` but Neo4j is down, Graph-related calls may error or return empty; prefer the flag for a clean RAG-only setup.

## KB graph vs chat memory

Graphiti episodes are split across two `group_id`s so the KB graph stays clean:

- **`GRAPHITI_GROUP_ID`** (default `llama-index-poc-kb`) — populated by `/ingest`. This is the only group rendered in `/graph/snapshot` and the Cytoscape canvas.
- **`GRAPHITI_CHAT_GROUP_ID`** (default `llama-index-poc-chat`) — populated only when `ENABLE_CHAT_EPISODES=true`. Each chat turn becomes a `message` episode here.

Default is `ENABLE_CHAT_EPISODES=false`, so chat turns are not pushed into Graphiti at all and the graph stays a pure document KB. Flip the flag on if you want cross-session chat memory; `search_facts` will then pull from both groups during answer grounding, but the canvas still only shows KB nodes because the snapshot query filters on `GRAPHITI_GROUP_ID`. To wipe chat memory without touching the KB:

```powershell
docker exec -it llama-index-poc-neo4j cypher-shell -u neo4j -p <your-neo4j-password> `
  "MATCH (n) WHERE n.group_id = 'llama-index-poc-chat' DETACH DELETE n"
```

## API Endpoints

- `GET  /health` — includes `graphiti_enabled` flag
- `GET  /kb/files?docs_dir=<optional_path>`
- `GET  /kb/debug?docs_dir=<optional_path>`
- `POST /upload` (multipart form: `files`, optional `docs_dir`)
- `POST /ingest` JSON: `{ "docs_dir": null | "C:\\abs\\path" }` — also pushes docs into Graphiti when enabled
- `POST /chat` JSON: `{ "question": "...", "history": ["optional previous user turns"] }` — response now includes `graph_facts`
- `GET  /graph/snapshot` — Cytoscape-shaped `{nodes, edges, enabled}` of the current graph
- `GET  /graph/stream` — Server-Sent Events stream of `episode_added` events for live UI updates

## How Data Is Stored

- Source docs: `backend/data/` (or custom `DOCS_DIR`)
- Chroma vectors: `backend/storage/chroma/`
- LlamaIndex persisted state: `backend/storage/llamaindex_store/`
- Graphiti graph: Neo4j (Docker volume `neo4j_data`)

## Resetting state (clean re-index)

To wipe both the vector index and the knowledge graph and start fresh:

1. **Stop the backend** (Ctrl+C the uvicorn process) so nothing is holding files or writing to Neo4j.
2. **Wipe LlamaIndex + Chroma** by deleting the persisted dirs. Removing `llamaindex_store/` is what forces `build_or_update_index` into the full-rebuild path; otherwise it tries an incremental refresh against a stale docstore.
   ```powershell
   Remove-Item -Recurse -Force .\backend\storage\chroma
   Remove-Item -Recurse -Force .\backend\storage\llamaindex_store
   ```
3. **Wipe Neo4j** — pick one:
   - *Full reset (drops the Docker volume):*
     ```powershell
     docker compose down -v
     docker compose up -d neo4j
     ```
   - *Clear only this project's group (keeps other Graphiti groups in the same Neo4j):*
     ```powershell
     docker exec -it llama-index-poc-neo4j cypher-shell -u neo4j -p <your-neo4j-password> `
       "MATCH (n) WHERE n.group_id = 'llama-index-poc-kb' DETACH DELETE n"
     ```
4. **Restart and re-ingest** (from `backend/` with venv active, or use your usual uvicorn command):
   ```powershell
   cd backend
   uv run uvicorn app.main:app --reload --port 8000
   ```
   Then in another shell: `curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d "{}"`
5. **Verify:** `GET /kb/debug` should report a fresh `vector_count`; `GET /graph/snapshot` will grow over the next ~30s as Graphiti's background pass (bounded by `Semaphore(2)`) extracts entities from each episode via Gemini.

## Try the temporal-update demo

Intentionally contradicting sample docs exercise Graphiti’s bi-temporal behavior. Stage them under `backend/data/` or `backend/data/demo/` and ingest in two waves (April, then October) to watch stale edges pick up `invalid_at` and render as dotted-red lines in the UI. Full walkthrough: [`README_demo.md`](README_demo.md) at the repo root.

## Notes

- PDF extraction uses `pypdf` before indexing.
- Incremental ingest refreshes changed/new docs in Chroma; stale-doc deletion is skipped when unsupported by the vector store integration.
- Graphiti's entity/relationship extraction is LLM-bound (uses Gemini), so first-time ingest of large corpora costs tokens and time.
- For best results, prefer clean `.md`/`.txt` runbooks and incident docs with consistent service naming — Graphiti's entity dedup works better when the same thing is named the same way across docs.
