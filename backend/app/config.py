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
