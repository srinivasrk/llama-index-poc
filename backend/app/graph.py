from __future__ import annotations

import os
from typing import TypedDict

from langgraph.graph import END, StateGraph
from llama_index.core import Settings
from llama_index.embeddings.gemini import GeminiEmbedding
from llama_index.llms.gemini import Gemini

from app.config import settings
from app.guardrails import is_grounded, refusal_message, should_refuse
from app.retrieval import retrieve_context


class ChatState(TypedDict):
    question: str
    history: list[str]
    context_chunks: list[dict]
    answer: str
    citations: list[dict]


def _configure_llm() -> None:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    Settings.llm = Gemini(model="models/gemini-2.5-flash")
    Settings.embed_model = GeminiEmbedding(model_name="models/gemini-embedding-2")


def retrieve_node(state: ChatState) -> ChatState:
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
    context_chunks = retrieve_context(retrieval_query)
    return {**state, "context_chunks": context_chunks}


def answer_guarded_node(state: ChatState) -> ChatState:
    if should_refuse(state["context_chunks"]):
        return {**state, "answer": refusal_message(), "citations": []}

    _configure_llm()
    context_block = "\n\n".join(
        f"[{i+1}] source={chunk['source']} score={chunk['score']:.3f}\n{chunk['text']}"
        for i, chunk in enumerate(state["context_chunks"])
    )
    prompt = f"""
You are a strict RAG assistant.
Rules:
1) Use ONLY the provided context.
2) If context is insufficient, answer exactly: {refusal_message()}
3) Keep answer concise and factual. For "who is/tell me about" questions, include a short profile with multiple concrete details from context.
4) End answer with citations in this format: [source:filename]

Question:
{state["question"]}

Context:
{context_block}
"""
    raw_answer = Settings.llm.complete(prompt).text.strip()
    if not is_grounded(raw_answer, state["context_chunks"]):
        raw_answer = refusal_message()
        citations: list[dict] = []
    else:
        # Multiple retrieved chunks often come from the same file.
        # Return one citation per source to avoid duplicate chips in the UI.
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
    return {**state, "answer": raw_answer, "citations": citations}


def build_chat_graph():
    graph_builder = StateGraph(ChatState)
    graph_builder.add_node("retrieve", retrieve_node)
    graph_builder.add_node("answer_guarded", answer_guarded_node)
    graph_builder.set_entry_point("retrieve")
    graph_builder.add_edge("retrieve", "answer_guarded")
    graph_builder.add_edge("answer_guarded", END)
    return graph_builder.compile()
