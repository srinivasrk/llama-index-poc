from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    gemini_api_key: str
    chroma_persist_dir: str = "./storage/chroma"
    docs_dir: str = "./data"
    top_k: int = 4
    similarity_cutoff: float = 0.5
    ingest_timeout_seconds: int = 180
    rag_fallback_message: str = "I don't know based on the provided knowledge base."

    # Graphiti / Neo4j. enable_graphiti=False keeps the original RAG-only flow
    # so the app still boots if Neo4j isn't running.
    enable_graphiti: bool = False
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "graphiti_dev_password"
    graphiti_group_id: str = "llama-index-poc"
    graphiti_search_top_k: int = 6
    # Model names used by Graphiti's Gemini client. Note: google-genai (new SDK)
    # naming, NOT google-generativeai. Embedding model must support embedContent.
    graphiti_llm_model: str = "gemini-2.5-flash"
    graphiti_embedding_model: str = "gemini-embedding-001"

    @property
    def docs_path(self) -> Path:
        return Path(self.docs_dir).resolve()

    @property
    def chroma_path(self) -> Path:
        return Path(self.chroma_persist_dir).resolve()

    @property
    def index_store_path(self) -> Path:
        return Path(self.chroma_persist_dir).resolve().parent / "llamaindex_store"


settings = Settings()
