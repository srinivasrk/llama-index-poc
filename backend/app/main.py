from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.graph import build_chat_graph
from app.ingest import COLLECTION_NAME, build_or_update_index, get_chroma_client, list_kb_files

app = FastAPI(title="LlamaIndex RAG PoC")
logger = logging.getLogger("uvicorn.error")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

chat_graph = build_chat_graph()


@app.middleware("http")
async def log_request_lifecycle(request, call_next):
    logger.info("Request started: %s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.info(
        "Request completed: %s %s -> %s",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


class IngestRequest(BaseModel):
    docs_dir: str | None = None


class ChatRequest(BaseModel):
    question: str
    history: list[str] | None = None


def _resolve_upload_dir(docs_dir: str | None) -> Path:
    base_dir = Path(docs_dir).resolve() if docs_dir else settings.docs_path
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/kb/files")
def kb_files(docs_dir: str | None = None) -> dict:
    return {"files": list(list_kb_files(docs_dir))}


@app.get("/kb/debug")
def kb_debug(docs_dir: str | None = None) -> dict:
    base_dir = _resolve_upload_dir(docs_dir)
    files_on_disk = list(list_kb_files(str(base_dir)))
    debug: dict = {
        "status": "ok",
        "docs_dir": str(base_dir),
        "chroma_path": str(settings.chroma_path),
        "index_store_path": str(settings.index_store_path),
        "collection_name": COLLECTION_NAME,
        "files_on_disk_count": len(files_on_disk),
        "files_on_disk": files_on_disk,
    }
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection(COLLECTION_NAME)
        vector_count = collection.count()
        sources: set[str] = set()
        try:
            rows = collection.get(include=["metadatas"], limit=max(vector_count, 1))
            for metadata in rows.get("metadatas", []) or []:
                if not metadata:
                    continue
                source = metadata.get("file_name") or metadata.get("file_path")
                if source:
                    sources.add(str(source))
        except Exception as exc:
            logger.warning("Unable to inspect Chroma metadatas for /kb/debug: %s", exc)
        debug.update(
            {
                "vector_count": vector_count,
                "indexed_sources_count": len(sources),
                "indexed_sources": sorted(sources),
            }
        )
    except Exception as exc:
        debug["vector_store_error"] = str(exc)
    return debug


@app.post("/ingest")
async def ingest(payload: IngestRequest) -> dict:
    import asyncio
    try:
        logger.info("Received /ingest request (docs_dir=%s)", payload.docs_dir)
        loop = asyncio.get_running_loop()
        timeout_s = settings.ingest_timeout_seconds
        logger.info("Dispatching ingest worker with timeout=%ss", timeout_s)
        return await asyncio.wait_for(
            loop.run_in_executor(None, build_or_update_index, payload.docs_dir),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError as exc:
        logger.error("Ingest request timed out after %ss", settings.ingest_timeout_seconds)
        raise HTTPException(
            status_code=504,
            detail=f"Ingest timed out after {settings.ingest_timeout_seconds}s",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    docs_dir: str | None = Form(default=None),
) -> dict:
    try:
        logger.info(
            "Received /upload request (files=%d, docs_dir=%s)",
            len(files),
            docs_dir,
        )
        target_dir = _resolve_upload_dir(docs_dir)
        uploaded: list[str] = []
        for file in files:
            safe_name = Path(file.filename or "uploaded_file").name
            suffix = Path(safe_name).suffix.lower()
            if suffix not in {".txt", ".md", ".pdf"}:
                logger.info("Skipping unsupported upload: %s", safe_name)
                continue

            dest = target_dir / safe_name
            logger.info("Reading upload into memory: %s", safe_name)
            content = await file.read()
            logger.info("Writing %s (%d bytes) to %s", safe_name, len(content), dest)
            dest.write_bytes(content)
            uploaded.append(safe_name)
            await file.close()

        logger.info("Upload complete: %d accepted file(s)", len(uploaded))
        return {
            "status": "ok",
            "uploaded_count": len(uploaded),
            "uploaded_files": uploaded,
            "source_dir": str(target_dir),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/chat")
def chat(payload: ChatRequest) -> dict:
    try:
        state = {
            "question": payload.question,
            "history": payload.history or [],
            "context_chunks": [],
            "answer": "",
            "citations": [],
        }
        output = chat_graph.invoke(state)
        return {"answer": output["answer"], "citations": output["citations"]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
