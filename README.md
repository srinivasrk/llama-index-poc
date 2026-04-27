# LlamaIndex + LangGraph + Graphiti RAG PoC (Gemini + Chroma + Neo4j + Next.js)

Local proof of concept for a hybrid RAG assistant grounded in two retrieval paths:

- **Backend**: FastAPI + LlamaIndex + LangGraph (async)
- **LLM/Embeddings**: Gemini
- **Vector store**: Chroma (persistent)
- **Knowledge graph**: Graphiti on Neo4j (temporal, bi-temporal edges)
- **Frontend**: Next.js with a live Cytoscape graph viz

The assistant answers from retrieved knowledge base chunks **and** Graphiti facts. If both are empty it refuses. Graphiti facts can ground answers vector search misses (especially across sessions), and edges that get superseded over time are kept and marked `invalid_at` rather than deleted — so the assistant can correctly answer *"what used to depend on Postgres?"*.

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
- Query via chat with citations (`/chat`) — answers are grounded by both vector chunks and graph facts
- Every chat turn is pushed back into Graphiti so memory accumulates across sessions
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

## Prerequisites

- Python 3.10+
- Node.js 20+
- Docker (for Neo4j)
- Gemini API key

## Quick start

```bash
# 1. Start Neo4j (skip if you don't want Graphiti — see "Disabling Graphiti" below)
docker compose up -d neo4j

# 2. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# edit backend/.env: set GEMINI_API_KEY, leave NEO4J_* defaults if using docker-compose
uv run uvicorn app.main:app --reload --port 8000

# 3. Frontend (new shell)
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`. Open Neo4j Browser at `http://localhost:7474` (default creds `neo4j` / `graphiti_dev_password`) if you want to inspect the graph independently.

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
GRAPHITI_GROUP_ID=llama-index-poc
```

## Disabling Graphiti

Set `ENABLE_GRAPHITI=false` in `backend/.env` (or just don't start Neo4j) and the app falls back to the original Chroma-only RAG flow. Graphiti calls become no-ops and the graph panel in the UI shows an "offline" badge — nothing else breaks.

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

## Try the temporal-update demo

A small set of intentionally-contradicting docs lives in `backend/data/demo/`. Ingest in two waves (April docs, then October docs) to watch Graphiti invalidate stale edges in real time while preserving historical truth. See `backend/data/demo/README_demo.md` for the full flow.

## Notes

- PDF extraction uses `pypdf` before indexing.
- Incremental ingest refreshes changed/new docs in Chroma; stale-doc deletion is skipped when unsupported by the vector store integration.
- Graphiti's entity/relationship extraction is LLM-bound (uses Gemini), so first-time ingest of large corpora costs tokens and time.
- For best results, prefer clean `.md`/`.txt` runbooks and incident docs with consistent service naming — Graphiti's entity dedup works better when the same thing is named the same way across docs.
