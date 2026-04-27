from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app import graphiti_client
from app.config import settings
from app.graph import build_chat_graph
from app.ingest import (
    COLLECTION_NAME,
    build_or_update_index,
    get_chroma_client,
    iter_text_documents,
    list_kb_files,
)

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Eagerly init Graphiti so the first request doesn't pay the cold-start cost.
    if settings.enable_graphiti:
        await graphiti_client.get_graphiti()
    try:
        yield
    finally:
        # Drain any in-flight background tasks (ingest + chat episodes) before
        # closing the Neo4j driver.
        from app.graph import _CHAT_BG_TASKS
        pending = list(_GRAPHITI_BG_TASKS) + list(_CHAT_BG_TASKS)
        if pending:
            logger.info("Waiting up to 30s for %d Graphiti background task(s)", len(pending))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Graphiti background tasks did not finish in time; cancelling")
                for t in pending:
                    t.cancel()
        await graphiti_client.close_graphiti()


app = FastAPI(title="LlamaIndex RAG PoC", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

chat_graph = build_chat_graph()

# Background ingest task tracking — keep hard refs so asyncio doesn't GC them.
_GRAPHITI_BG_TASKS: "set[asyncio.Task]" = set()


async def _ingest_docs_to_graphiti(docs_dir: "str | None") -> None:
    """Push each on-disk doc into Graphiti as a text episode.

    Bounded concurrency (semaphore=2) avoids hammering Gemini. Each episode
    fires `episode_added` over /graph/stream so the GraphPanel updates live.
    """
    sem = asyncio.Semaphore(2)
    docs = iter_text_documents(docs_dir)
    if not docs:
        return

    graphiti_client._broadcast({"type": "ingest_started", "total": len(docs)})

    async def _one(name: str, text: str, path: str) -> bool:
        async with sem:
            return await graphiti_client.add_doc_episode(name, text, path)

    results = await asyncio.gather(
        *[_one(n, t, p) for n, t, p in docs],
        return_exceptions=True,
    )
    added = sum(1 for r in results if r is True)
    failed = sum(1 for r in results if r is not True)
    logger.info("Graphiti background ingest complete: %d added, %d failed", added, failed)
    graphiti_client._broadcast({"type": "ingest_complete", "added": added, "failed": failed})


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
    docs_dir: "str | None" = None


class ChatRequest(BaseModel):
    question: str
    history: "list[str] | None" = None


def _resolve_upload_dir(docs_dir: "str | None") -> Path:
    base_dir = Path(docs_dir).resolve() if docs_dir else settings.docs_path
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "graphiti_enabled": graphiti_client.is_enabled()}


@app.get("/kb/files")
def kb_files(docs_dir: "str | None" = None) -> dict:
    return {"files": list(list_kb_files(docs_dir))}


@app.get("/kb/debug")
def kb_debug(docs_dir: "str | None" = None) -> dict:
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
        sources: set = set()
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
        debug.update({
            "vector_count": vector_count,
            "indexed_sources_count": len(sources),
            "indexed_sources": sorted(sources),
        })
    except Exception as exc:
        debug["vector_store_error"] = str(exc)
    return debug


@app.post("/ingest")
async def ingest(payload: IngestRequest) -> dict:
    try:
        logger.info("Received /ingest request (docs_dir=%s)", payload.docs_dir)
        loop = asyncio.get_running_loop()
        timeout_s = settings.ingest_timeout_seconds
        logger.info("Dispatching ingest worker with timeout=%ss", timeout_s)
        result = await asyncio.wait_for(
            loop.run_in_executor(None, build_or_update_index, payload.docs_dir),
            timeout=timeout_s,
        )

        # Hand the Graphiti pass off to the background. The frontend's SSE
        # subscription on /graph/stream surfaces live progress.
        if graphiti_client.is_enabled():
            task = asyncio.create_task(_ingest_docs_to_graphiti(payload.docs_dir))
            _GRAPHITI_BG_TASKS.add(task)
            task.add_done_callback(_GRAPHITI_BG_TASKS.discard)
            result["graphiti_status"] = "queued"
            result["graphiti_in_progress"] = len(_GRAPHITI_BG_TASKS)
        return result
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
    files: "list[UploadFile]" = File(...),
    docs_dir: "str | None" = Form(default=None),
) -> dict:
    try:
        logger.info(
            "Received /upload request (files=%d, docs_dir=%s)",
            len(files),
            docs_dir,
        )
        target_dir = _resolve_upload_dir(docs_dir)
        uploaded: list = []
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
async def chat(payload: ChatRequest) -> dict:
    try:
        state = {
            "question": payload.question,
            "history": payload.history or [],
            "context_chunks": [],
            "graph_facts": [],
            "answer": "",
            "citations": [],
        }
        output = await chat_graph.ainvoke(state)
        return {
            "answer": output["answer"],
            "citations": output["citations"],
            "graph_facts": output.get("graph_facts", []),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------- Graphiti graph endpoints ---------------------- #


@app.get("/graph/snapshot")
async def graph_snapshot() -> dict:
    return await graphiti_client.snapshot()


@app.get("/graph/stream")
async def graph_stream(request: Request):
    async def _event_gen() -> "AsyncIterator[dict]":
        queue = graphiti_client.subscribe()
        try:
            yield {"event": "hello", "data": json.dumps({"enabled": graphiti_client.is_enabled()})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": event.get("type", "change"), "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            graphiti_client.unsubscribe(queue)

    return EventSourceResponse(_event_gen())
