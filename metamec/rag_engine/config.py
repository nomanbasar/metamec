"""
Centralized configuration for rag_engine.

Loads everything from environment variables (via python-dotenv locally).
In the Django integration, these can instead be sourced from Django settings —
just make sure the same env vars are present in the process environment,
or adapt `Settings.from_env()` to read from `django.conf.settings`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # WordPress
    wp_base_url: str
    wp_app_username: str
    wp_app_password: str
    wp_post_types: list[str]

    # OpenAI
    openai_api_key: str
    openai_embedding_model: str
    openai_chat_model: str

    # ChromaDB
    chroma_persist_dir: str
    chroma_collection_name: str

    # Chunking
    chunk_size: int
    chunk_overlap: int

    # Retrieval
    retrieval_top_k: int

    @classmethod
    def from_env(cls) -> "Settings":
        def _require(key: str) -> str:
            val = os.getenv(key)
            if not val:
                raise RuntimeError(f"Missing required environment variable: {key}")
            return val

        return cls(
            wp_base_url=_require("WP_BASE_URL").rstrip("/"),
            wp_app_username=_require("WP_APP_USERNAME"),
            wp_app_password=_require("WP_APP_PASSWORD"),
            wp_post_types=[
                pt.strip()
                for pt in os.getenv("WP_POST_TYPES", "pages").split(",")
                if pt.strip()
            ],
            openai_api_key=_require("OPENAI_API_KEY"),
            openai_embedding_model=os.getenv(
                "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            openai_chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
            chroma_persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"),
            chroma_collection_name=os.getenv(
                "CHROMA_COLLECTION_NAME", "dragon_finance_kb"
            ),
            chunk_size=int(os.getenv("CHUNK_SIZE", "800")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "120")),
            retrieval_top_k=int(os.getenv("RETRIEVAL_TOP_K", "4")),
        )


settings = Settings.from_env()
