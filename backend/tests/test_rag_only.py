from __future__ import annotations

import asyncio
import os

import pytest

from app.config import settings
from app.graph import build_chat_graph
from app.ingest import build_or_update_index


def _initial_state(question: str) -> dict:
    return {
        "question": question,
        "history": [],
        "context_chunks": [],
        "graph_facts": [],
        "answer": "",
        "citations": [],
    }


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY") and not getattr(settings, "gemini_api_key", ""),
    reason="Requires GEMINI_API_KEY to run",
)
def test_rag_only_refuses_out_of_kb():
    build_or_update_index()
    graph = build_chat_graph()
    out = asyncio.run(graph.ainvoke(_initial_state("What is the capital of France?")))
    assert "I don't know based on the provided knowledge base." in out["answer"]


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY") and not getattr(settings, "gemini_api_key", ""),
    reason="Requires GEMINI_API_KEY to run",
)
def test_answers_in_kb_with_citations():
    build_or_update_index()
    graph = build_chat_graph()
    out = asyncio.run(graph.ainvoke(_initial_state("What is the project codename?")))
    assert "BluePine" in out["answer"]
    assert "[source:" in out["answer"].lower()
