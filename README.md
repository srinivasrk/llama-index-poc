# LlamaIndex + LangGraph RAG PoC (Gemini + Chroma + Next.js)

Local proof of concept for a strict RAG assistant:

- **Backend**: FastAPI + LlamaIndex + LangGraph
- **LLM/Embeddings**: Gemini
- **Vector store**: Chroma (persistent)
- **Frontend**: Next.js

The assistant is designed to answer **only from retrieved knowledge base chunks**. If context is insufficient, it refuses.

## Current Features

- Upload `.md`, `.txt`, `.pdf` documents from the UI (`/upload`)
- Ingest/index documents into Chroma (`/ingest`)
- Query via chat with citations (`/chat`)
- Conversation-aware retrieval (recent user turns included in retrieval query)
- Guardrail-based refusal for insufficient grounding
- Debug endpoint to inspect index state (`/kb/debug`)

## Prerequisites

- Python 3.10+
- Node.js 20+
- Gemini API key

## Backend Setup (FastAPI)

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Set `backend/.env`:

- `GEMINI_API_KEY=...`
- optional tuning:
  - `TOP_K`
  - `SIMILARITY_CUTOFF`
  - `RAG_FALLBACK_MESSAGE`

Run backend:

```bash
cd backend
.\.venv\Scripts\activate
uv run uvicorn app.main:app --reload --port 8000
```

## Frontend Setup (Next.js)

```bash
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`.

## API Endpoints

- `GET /health`
- `GET /kb/files?docs_dir=<optional_path>`
- `GET /kb/debug?docs_dir=<optional_path>`
- `POST /upload` (multipart form: `files`, optional `docs_dir`)
- `POST /ingest` JSON: `{ "docs_dir": null | "C:\\abs\\path" }`
- `POST /chat` JSON: `{ "question": "...", "history": ["optional previous user turns"] }`

## How Data Is Stored

- Source docs: `backend/data/` (or custom `DOCS_DIR`)
- Chroma vectors: `backend/storage/chroma/`
- LlamaIndex persisted state: `backend/storage/llamaindex_store/`

## Notes

- PDF extraction uses `pypdf` before indexing.
- Incremental ingest refreshes changed/new docs; stale-doc deletion is skipped when unsupported by vector store integration.
- For best results, prefer clean `.md`/`.txt` runbooks and incident docs with consistent service naming.
