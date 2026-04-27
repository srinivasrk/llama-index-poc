from __future__ import annotations

import asyncio
import logging
import os
from typing import TypedDict

from langgraph.graph import END, StateGraph
from llama_index.core import Settings
from llama_index.embeddings.gemini import GeminiEmbedding
from llama_index.llms.gemini import Gemini

from app import graphiti_client
from app.config import settings
from app.guardrails import is_grounded, refusal_message, should_refuse
from app.retrieval import retrieve_context, retrieve_facts

logger = logging.getLogger("uvicorn.error")

# Hard refs to fire-and-forget chat-episode tasks. asyncio only weakly tracks
# create_task results, so without this set the GC could collect them mid-flight.
_CHAT_BG_TASKS: "set[asyncio.Task]" = set()


def _schedule_chat_episode(question: str, answer: str) -> None:
    """Push a chat turn into Graphiti without blocking the response.

    Graphiti's add_episode runs LLM extraction (~10-25s on Gemini) which the
    user has no reason to wait for. The background task fires an
    `episode_added` SSE event when it lands; the GraphPanel re-fetches and
    flashes the new nodes/edges then.
    """
    if not graphiti_client.is_enabled():
        return
    task = asyncio.create_task(graphiti_client.add_chat_episode(question, answer))
    _CHAT_BG_TASKS.add(task)
    task.add_done_callback(_CHAT_BG_TASKS.discard)


class ChatState(TypedDict):
    question: str
    history: list[str]
    context_chunks: list[dict]
    graph_facts: list[dict]
    answer: str
    citations: list[dict]


def _configure_llm() -> None:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    Settings.llm = Gemini(model="models/gemini-2.5-flash")
    Settings.embed_model = GeminiEmbedding(model_name="models/gemini-embedding-2")


async def retrieve_node(state: ChatState) -> ChatState:
    question = state["question"]
    history = [h.strip() for h in state.get("history", []) if h and h.strip()]
    retrieval_query = question
    lowered = question.lower().strip()
    if lowered.startswith("who is ") or lowered.startswith("tell me about "):
        retrieval_query = (
            f"{question}\n"
            "Focus on profile details: background, role, experience, skills, achievements, education."
        )
    if history:
        recent_history = " | ".join(history[-3:])
        retrieval_query = f"Conversation context: {recent_history}\nCurrent question: {question}"

    # Vector chunks (sync — pushed to thread pool) and graph facts (async)
    # run in parallel so we wait on the slower of the two, not their sum.
    loop = asyncio.get_running_loop()
    chunks_future = loop.run_in_executor(None, retrieve_context, retrieval_query)
    facts_future = retrieve_facts(retrieval_query)
    context_chunks, graph_facts = await asyncio.gather(chunks_future, facts_future)
    return {**state, "context_chunks": context_chunks, "graph_facts": graph_facts}


async def answer_guarded_node(state: ChatState) -> ChatState:
    facts = state.get("graph_facts") or []

    # Refuse only when BOTH retrieval paths come up empty. Graphiti facts can
    # ground an answer the vector store missed (e.g. cross-session memory).
    if should_refuse(state["context_chunks"]) and not facts:
        answer = refusal_message()
        # Still record the turn so Graphiti remembers the question was asked.
        _schedule_chat_episode(state["question"], answer)
        return {**state, "answer": answer, "citations": []}

    _configure_llm()
    context_block = "\n\n".join(
        f"[{i+1}] source={chunk['source']} score={chunk['score']:.3f}\n{chunk['text']}"
        for i, chunk in enumerate(state["context_chunks"])
    )
    facts_block = ""
    if facts:
        facts_block = "\n\nKnowledge graph facts (from Graphiti, may include cross-session memory):\n" + "\n".join(
            f"- {f.get('fact', '')}"
            + (f"  [valid_at={f['valid_at']}]" if f.get("valid_at") else "")
            + (f"  [invalid_at={f['invalid_at']}]" if f.get("invalid_at") else "")
            for f in facts
            if f.get("fact")
        )

    prompt = f"""
You are a strict RAG assistant.
Rules:
1) Use ONLY the provided context (vector chunks AND knowledge graph facts).
2) If context is insufficient, answer exactly: {refusal_message()}
3) Keep answer concise and factual. For "who is/tell me about" questions, include a short profile with multiple concrete details from context.
4) End answer with citations in this format: [source:filename]
5) If a knowledge graph fact contradicts an older chunk, prefer the graph fact (it has temporal info).

Question:
{state["question"]}

Context (vector chunks):
{context_block}
{facts_block}
"""
    raw_answer = Settings.llm.complete(prompt).text.strip()
    if not is_grounded(raw_answer, state["context_chunks"]) and not facts:
        raw_answer = refusal_message()
        citations: list[dict] = []
    else:
        unique_citations: dict[str, dict] = {}
        for chunk in state["context_chunks"]:
            source = chunk["source"]
            best = unique_citations.get(source)
            if best is None or float(chunk["score"]) > float(best["score"]):
                unique_citations[source] = {
                    "source": source,
                    "score": chunk["score"],
                    "node_id": chunk["node_id"],
                }
        citations = list(unique_citations.values())

    # Push the turn into Graphiti so future retrieval can pull it back.
    # Fire-and-forget: the user gets their answer immediately, and the
    # extraction work happens in the background.
    _schedule_chat_episode(state["question"], raw_answer)

    return {**state, "answer": raw_answer, "citations": citations}


def build_chat_graph():
    graph_builder = StateGraph(ChatState)
    graph_builder.add_node("retrieve", retrieve_node)
    graph_builder.add_node("answer_guarded", answer_guarded_node)
    graph_builder.set_entry_point("retrieve")
    graph_builder.add_edge("retrieve", "answer_guarded")
    graph_builder.add_edge("answer_guarded", END)
    return graph_builder.compile()
