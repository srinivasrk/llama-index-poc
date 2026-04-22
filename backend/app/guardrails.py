from __future__ import annotations

import re

from app.config import settings


def should_refuse(context_chunks: list[dict]) -> bool:
    return len(context_chunks) == 0


_CITATION_RE = re.compile(r"\[source:[^\]]+\]", re.IGNORECASE)


def has_citations(answer: str) -> bool:
    return bool(_CITATION_RE.search(answer))


def is_grounded(answer: str, context_chunks: list[dict]) -> bool:
    if not answer.strip():
        return False
    if not has_citations(answer):
        return False

    lowered = answer.lower()
    # Require some lexical overlap with retrieved text to avoid free-form hallucinations.
    # This is intentionally conservative for a PoC; it can be improved later with entailment checks.
    for chunk in context_chunks:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        snippet = text[:300].lower()
        if any(tok in snippet for tok in lowered.split()[:18]):
            return True
    return False


def refusal_message() -> str:
    return settings.rag_fallback_message
