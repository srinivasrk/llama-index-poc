from __future__ import annotations

import logging
import os
from pathlib import Path
from time import perf_counter
from typing import Iterable

import chromadb
from chromadb.api import ClientAPI
from llama_index.core import (
    Settings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.schema import Document
from llama_index.embeddings.gemini import GeminiEmbedding
from llama_index.llms.gemini import Gemini
from llama_index.vector_stores.chroma import ChromaVectorStore
from pypdf import PdfReader

from app.config import settings

COLLECTION_NAME = "kb_chunks"
# Use uvicorn's logger so INFO messages appear in the running backend terminal.
logger = logging.getLogger("uvicorn.error")


def _configure_models() -> None:
    logger.info("Configuring Gemini LLM and embedding models")
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    Settings.llm = Gemini(model="models/gemini-2.5-flash")
    Settings.embed_model = GeminiEmbedding(model_name="models/gemini-embedding-001")


def get_chroma_client() -> ClientAPI:
    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    logger.info("Connecting to ChromaDB at %s", settings.chroma_path)
    return chromadb.PersistentClient(path=str(settings.chroma_path))


def _load_documents(docs_dir: Path) -> list[Document]:
    logger.info("Loading documents from %s", docs_dir)
    start = perf_counter()
    docs: list[Document] = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in {".txt", ".md", ".pdf"}:
            continue
        try:
            if suffix == ".pdf":
                reader = PdfReader(str(path))
                page_text = [(page.extract_text() or "") for page in reader.pages]
                text = "\n\n".join(chunk for chunk in page_text if chunk.strip())
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            logger.exception("Failed to read %s: %s", path, exc)
            continue

        if not text.strip():
            logger.info("Skipping empty document after extraction: %s", path)
            continue

        docs.append(
            Document(
                text=text,
                metadata={"file_name": path.name, "file_path": str(path)},
                doc_id=str(path.resolve()),
            )
        )
    logger.info(
        "Loaded %d document(s) from %s in %.2fs",
        len(docs),
        docs_dir,
        perf_counter() - start,
    )
    return docs


def _full_rebuild(
    docs: list[Document],
    client: ClientAPI,
    persist_dir: str,
) -> tuple[VectorStoreIndex, set[str]]:
    """Wipe the collection and re-index everything from scratch."""
    logger.info("Starting full rebuild for %d document(s)", len(docs))
    start = perf_counter()
    try:
        logger.info("Deleting existing Chroma collection '%s'", COLLECTION_NAME)
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        logger.info("Collection '%s' did not exist; skipping delete", COLLECTION_NAME)
    collection = client.create_collection(COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    settings.index_store_path.mkdir(parents=True, exist_ok=True)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    logger.info("Building vector index from %d document(s) (embedding + upsert phase)", len(docs))
    build_start = perf_counter()
    index = VectorStoreIndex.from_documents(documents=docs, storage_context=storage_context)
    logger.info("Vector index build phase finished in %.2fs", perf_counter() - build_start)
    logger.info("Full rebuild completed in %.2fs", perf_counter() - start)
    return index, set()


def build_or_update_index(docs_dir: str | None = None) -> dict:
    overall_start = perf_counter()
    logger.info("Starting ingest run (docs_dir=%s)", docs_dir or str(settings.docs_path))
    _configure_models()
    base_dir = Path(docs_dir).resolve() if docs_dir else settings.docs_path
    if not base_dir.exists():
        raise FileNotFoundError(f"Knowledge base path not found: {base_dir}")

    docs = _load_documents(base_dir)
    if not docs:
        raise ValueError(f"No supported files found in: {base_dir}")
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("file_name") or doc.metadata.get("file_path") or doc.doc_id or f"doc-{i}"
        logger.info(
            "Document %d/%d ready for indexing: source=%s chars=%d",
            i,
            len(docs),
            source,
            len(doc.text or ""),
        )

    client = get_chroma_client()
    persist_dir = str(settings.index_store_path)

    index: VectorStoreIndex | None = None
    deleted_ids: set[str] = set()
    num_refreshed = len(docs)
    mode = "full"

    if (settings.index_store_path / "docstore.json").exists():
        try:
            logger.info("Attempting incremental ingest using existing docstore")
            collection = client.get_or_create_collection(COLLECTION_NAME)
            vector_store = ChromaVectorStore(chroma_collection=collection)
            storage_context = StorageContext.from_defaults(
                vector_store=vector_store,
                persist_dir=persist_dir,
            )
            index = load_index_from_storage(storage_context)

            # Remove chunks for files that no longer exist on disk.
            # Some vector stores (including Chroma with stored text) do not support ref_doc_info.
            try:
                current_doc_ids = {doc.doc_id for doc in docs}
                deleted_ids = set(index.ref_doc_info.keys()) - current_doc_ids
                logger.info("Detected %d stale document(s) to delete", len(deleted_ids))
                for stale_id in deleted_ids:
                    index.delete_ref_doc(stale_id, delete_from_docstore=True)
            except NotImplementedError:
                deleted_ids = set()
                logger.info(
                    "Skipping stale-doc deletion: ref_doc_info is unsupported by this vector store integration"
                )

            # Insert new docs; re-embed any whose content hash changed; skip unchanged
            logger.info("Starting incremental refresh (embedding + upsert for changed/new docs)")
            refresh_start = perf_counter()
            refreshed = index.refresh_ref_docs(docs)
            num_refreshed = sum(1 for r in refreshed if r)
            logger.info(
                "Incremental refresh finished in %.2fs; refreshed %d of %d document(s)",
                perf_counter() - refresh_start,
                num_refreshed,
                len(docs),
            )
            mode = "incremental"
        except Exception as exc:
            # Docstore is inconsistent with ChromaDB state — fall back to full rebuild
            logger.exception("Incremental ingest failed, falling back to full rebuild: %s", exc)
            index = None
            deleted_ids = set()
            num_refreshed = len(docs)
            mode = "full (rebuilt after error: " + str(exc)[:120] + ")"

    if index is None:
        index, deleted_ids = _full_rebuild(docs, client, persist_dir)

    logger.info("Persisting index state to %s", persist_dir)
    index.storage_context.persist(persist_dir=persist_dir)
    logger.info(
        "Ingest run complete in %.2fs (mode=%s, indexed=%d, refreshed=%d, deleted=%d)",
        perf_counter() - overall_start,
        mode,
        len(docs),
        num_refreshed,
        len(deleted_ids),
    )

    return {
        "status": "ok",
        "mode": mode,
        "documents_indexed": len(docs),
        "documents_refreshed": num_refreshed,
        "documents_deleted": len(deleted_ids),
        "collection_name": COLLECTION_NAME,
        "source_dir": str(base_dir),
        "doc_ids": [doc.doc_id for doc in docs if doc.doc_id],
        "index_class": index.__class__.__name__,
    }


def list_kb_files(docs_dir: str | None = None) -> Iterable[str]:
    base_dir = Path(docs_dir).resolve() if docs_dir else settings.docs_path
    if not base_dir.exists():
        return []
    return sorted(str(path.relative_to(base_dir)) for path in base_dir.rglob("*") if path.is_file())
