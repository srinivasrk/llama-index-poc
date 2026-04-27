from __future__ import annotations

import logging
import os
from typing import Any

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.embeddings.gemini import GeminiEmbedding
from llama_index.llms.gemini import Gemini
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.config import settings
from app.ingest import COLLECTION_NAME, get_chroma_client
from app import graphiti_client

logger = logging.getLogger("uvicorn.error")


async def retrieve_facts(query: str) -> list[dict[str, Any]]:
    """Return Graphiti edge-facts most relevant to `query`. Empty list if disabled."""
    facts = await graphiti_client.search_facts(query)
    if facts:
        logger.info("Graphiti returned %d fact(s) for query", len(facts))
    return facts


def _configure_models() -> None:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    Settings.llm = Gemini(model="models/gemini-2.5-flash")
    Settings.embed_model = GeminiEmbedding(model_name="models/gemini-embedding-001")


def _build_retriever() -> VectorIndexRetriever:
    _configure_models()
    client = get_chroma_client()
    collection = client.get_or_create_collection(COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    index = VectorStoreIndex.from_vector_store(vector_store)
    return index.as_retriever(similarity_top_k=settings.top_k)


def retrieve_context(query: str) -> list[dict[str, Any]]:
    retriever = _build_retriever()
    nodes = retriever.retrieve(query)

    candidates: list[dict[str, Any]] = []
    formatted: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for node in nodes:
        score = float(node.score or 0.0)
        metadata = node.metadata or {}
        node_id = node.node.node_id
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        item = {
            "score": score,
            "text": node.text,
            "source": metadata.get("file_name", metadata.get("file_path", "unknown")),
            "node_id": node_id,
        }
        candidates.append(item)
        if score >= settings.similarity_cutoff:
            formatted.append(item)

    min_context_chunks = 3
    if len(formatted) < min_context_chunks and candidates:
        remaining = [c for c in candidates if c["node_id"] not in {f["node_id"] for f in formatted}]
        needed = min(min_context_chunks - len(formatted), len(remaining))
        if needed > 0:
            formatted.extend(sorted(remaining, key=lambda x: x["score"], reverse=True)[:needed])

    if not formatted and candidates:
        # Fallback for follow-up questions where pronouns reduce semantic match scores.
        fallback_k = min(2, len(candidates))
        formatted = sorted(candidates, key=lambda x: x["score"], reverse=True)[:fallback_k]
        logger.info(
            "No chunks met similarity cutoff %.3f; using top-%d fallback chunk(s) (best score %.3f)",
            settings.similarity_cutoff,
            fallback_k,
            formatted[0]["score"],
        )
    logger.info(
        "Retrieved %d candidate chunk(s), returning %d chunk(s) for answer synthesis",
        len(candidates),
        len(formatted),
    )
    return formatted
