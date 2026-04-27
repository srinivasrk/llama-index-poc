"""Graphiti integration: temporal knowledge graph layer."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger("uvicorn.error")

try:
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType
    from graphiti_core.llm_client.gemini_client import GeminiClient
    try:
        from graphiti_core.llm_client.config import LLMConfig
    except ImportError:  # pragma: no cover
        from graphiti_core.llm_client.gemini_client import LLMConfig  # type: ignore[no-redef]
    from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
    try:
        from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
        _GEMINI_RERANKER_AVAILABLE = True
    except ImportError:  # pragma: no cover
        GeminiRerankerClient = None  # type: ignore[assignment]
        _GEMINI_RERANKER_AVAILABLE = False
    _GRAPHITI_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    logger.warning("graphiti-core not importable; Graphiti features disabled: %s", exc)
    Graphiti = None  # type: ignore[assignment]
    EpisodeType = None  # type: ignore[assignment]
    _GEMINI_RERANKER_AVAILABLE = False
    _GRAPHITI_AVAILABLE = False


_client: "Graphiti | None" = None
_init_lock = asyncio.Lock()
_init_failed = False
_subscribers: "list[asyncio.Queue[dict]]" = []


def is_enabled() -> bool:
    return bool(settings.enable_graphiti and _GRAPHITI_AVAILABLE)


async def get_graphiti() -> "Graphiti | None":
    global _client, _init_failed
    if not is_enabled() or _init_failed:
        return None
    if _client is not None:
        return _client
    async with _init_lock:
        if _client is not None:
            return _client
        try:
            llm_client = GeminiClient(
                config=LLMConfig(api_key=settings.gemini_api_key, model=settings.graphiti_llm_model)
            )
            embedder = GeminiEmbedder(
                config=GeminiEmbedderConfig(
                    api_key=settings.gemini_api_key,
                    embedding_model=settings.graphiti_embedding_model,
                )
            )
            cross_encoder = None
            if _GEMINI_RERANKER_AVAILABLE:
                cross_encoder = GeminiRerankerClient(
                    config=LLMConfig(api_key=settings.gemini_api_key, model=settings.graphiti_llm_model)
                )
            client = Graphiti(
                settings.neo4j_uri,
                settings.neo4j_user,
                settings.neo4j_password,
                llm_client=llm_client,
                embedder=embedder,
                cross_encoder=cross_encoder,
            )
            await client.build_indices_and_constraints()
            _client = client
            logger.info(
                "Graphiti client initialized (uri=%s, group_id=%s, llm=%s, emb=%s)",
                settings.neo4j_uri,
                settings.graphiti_group_id,
                settings.graphiti_llm_model,
                settings.graphiti_embedding_model,
            )
            return _client
        except Exception as exc:
            _init_failed = True
            logger.exception("Failed to initialize Graphiti: %s", exc)
            return None


async def close_graphiti() -> None:
    global _client
    if _client is not None:
        with suppress(Exception):
            await _client.close()
        _client = None


def subscribe() -> "asyncio.Queue[dict]":
    q: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=64)
    _subscribers.append(q)
    return q


def unsubscribe(q: "asyncio.Queue[dict]") -> None:
    with suppress(ValueError):
        _subscribers.remove(q)


def _broadcast(event: dict) -> None:
    for q in list(_subscribers):
        with suppress(asyncio.QueueFull):
            q.put_nowait(event)


async def add_doc_episode(name: str, content: str, source_path: str) -> bool:
    g = await get_graphiti()
    if g is None or EpisodeType is None:
        return False
    if not content.strip():
        return False
    try:
        await g.add_episode(
            name=name[:200],
            episode_body=content[:50_000],
            source=EpisodeType.text,
            source_description=f"document: {source_path}",
            reference_time=datetime.now(timezone.utc),
            group_id=settings.graphiti_group_id,
        )
        _broadcast({"type": "episode_added", "kind": "doc", "name": name})
        return True
    except Exception as exc:
        logger.exception("Graphiti add_doc_episode failed for %s: %s", name, exc)
        return False


async def add_chat_episode(question: str, answer: str, session_id: str = "default") -> bool:
    g = await get_graphiti()
    if g is None or EpisodeType is None:
        return False
    body = f"User: {question}\nAssistant: {answer}"
    try:
        await g.add_episode(
            name=f"chat::{session_id}::{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            episode_body=body,
            source=EpisodeType.message,
            source_description=f"chat session: {session_id}",
            reference_time=datetime.now(timezone.utc),
            group_id=settings.graphiti_group_id,
        )
        _broadcast({"type": "episode_added", "kind": "chat", "session_id": session_id})
        return True
    except Exception as exc:
        logger.exception("Graphiti add_chat_episode failed: %s", exc)
        return False


def _iso(value: Any) -> "str | None":
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _pretty_episode_label(raw: str) -> str:
    """Make episode labels nicer in the Cytoscape canvas."""
    if not raw:
        return "episode"
    if raw.startswith("chat::"):
        parts = raw.split("::")
        if len(parts) >= 3:
            ts = parts[-1]
            time_part = ts.split("T", 1)[1][:5] if "T" in ts else ts[:5]
            return f"chat - {time_part}"
        return "chat"
    base = raw.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return base[:60]


async def search_facts(query: str) -> "list[dict[str, Any]]":
    g = await get_graphiti()
    if g is None:
        return []
    try:
        results = await g.search(
            query=query,
            group_ids=[settings.graphiti_group_id],
            num_results=settings.graphiti_search_top_k,
        )
        out: "list[dict[str, Any]]" = []
        for r in results:
            out.append({
                "fact": getattr(r, "fact", "") or getattr(r, "name", ""),
                "uuid": getattr(r, "uuid", None),
                "valid_at": _iso(getattr(r, "valid_at", None)),
                "invalid_at": _iso(getattr(r, "invalid_at", None)),
            })
        return out
    except Exception as exc:
        logger.exception("Graphiti search failed: %s", exc)
        return []


CYPHER_ENTITIES = (
    "MATCH (n:Entity) WHERE n.group_id = $gid "
    "RETURN n.uuid AS id, coalesce(n.name, n.summary, '?') AS label, "
    "n.summary AS summary LIMIT $limit"
)
CYPHER_EPISODES = (
    # Only return episodes that actually link to at least one entity. Orphan
    # episodes (extraction failed or still in-flight) clutter the canvas.
    "MATCH (e:Episodic) "
    "WHERE e.group_id = $gid AND EXISTS { MATCH (e)-[:MENTIONS]->(:Entity) } "
    "RETURN e.uuid AS id, coalesce(e.name, 'episode') AS label, "
    "e.source AS source ORDER BY e.created_at DESC LIMIT $limit"
)
CYPHER_EDGES = (
    "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
    "WHERE a.group_id = $gid AND b.group_id = $gid "
    "RETURN r.uuid AS id, a.uuid AS source, b.uuid AS target, "
    "coalesce(r.name, r.fact, 'relates_to') AS label, "
    "r.fact AS fact, r.valid_at AS valid_at, r.invalid_at AS invalid_at "
    "LIMIT $limit"
)
CYPHER_MENTIONS = (
    "MATCH (e:Episodic)-[m:MENTIONS]->(n:Entity) "
    "WHERE e.group_id = $gid AND n.group_id = $gid "
    "RETURN coalesce(m.uuid, e.uuid + '->' + n.uuid) AS id, "
    "e.uuid AS source, n.uuid AS target LIMIT $limit"
)


async def snapshot(node_limit: int = 200) -> "dict[str, Any]":
    g = await get_graphiti()
    if g is None:
        return {"nodes": [], "edges": [], "enabled": False}
    nodes: list = []
    edges: list = []
    try:
        driver = g.driver
        async with driver.session() as session:
            res = await session.run(CYPHER_ENTITIES, gid=settings.graphiti_group_id, limit=node_limit)
            async for row in res:
                nodes.append({"data": {"id": row["id"], "label": row["label"], "kind": "entity", "summary": row.get("summary")}})
            res = await session.run(CYPHER_EPISODES, gid=settings.graphiti_group_id, limit=max(20, node_limit // 4))
            async for row in res:
                nodes.append({"data": {"id": row["id"], "label": _pretty_episode_label(row["label"] or ""), "kind": "episode", "source": row.get("source")}})
            res = await session.run(CYPHER_EDGES, gid=settings.graphiti_group_id, limit=node_limit * 2)
            async for row in res:
                edges.append({"data": {"id": row["id"], "source": row["source"], "target": row["target"], "label": row["label"], "fact": row.get("fact"), "valid_at": _iso(row.get("valid_at")), "invalid_at": _iso(row.get("invalid_at")), "kind": "relates_to"}})
            res = await session.run(CYPHER_MENTIONS, gid=settings.graphiti_group_id, limit=node_limit)
            async for row in res:
                edges.append({"data": {"id": row["id"], "source": row["source"], "target": row["target"], "label": "mentions", "kind": "mentions"}})
    except Exception as exc:
        logger.exception("Graphiti snapshot query failed: %s", exc)
        return {"nodes": [], "edges": [], "enabled": True, "error": str(exc)}
    return {"nodes": nodes, "edges": edges, "enabled": True}
