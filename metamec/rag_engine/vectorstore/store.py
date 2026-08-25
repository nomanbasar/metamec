"""
ChromaDB vector store wrapper.

Uses a persistent local Chroma client by default. For the Django integration,
point CHROMA_PERSIST_DIR at a stable, writable path (or swap
`chromadb.PersistentClient` for `chromadb.HttpClient` to talk to a
standalone Chroma server — same interface below, just change `_build_client`).
"""

from __future__ import annotations

import logging
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from ..config import Settings
from ..ingestion.chunker import Chunk

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = self._build_client()
        self._embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
            api_key=settings.openai_api_key,
            model_name=settings.openai_embedding_model,
        )
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection_name,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def _build_client(self) -> chromadb.ClientAPI:
        return chromadb.PersistentClient(path=self.settings.chroma_persist_dir)

    # -- Write path -----------------------------------------------------

    def upsert_chunks(self, chunks: list[Chunk], batch_size: int = 100) -> None:
        """Embed + upsert chunks. Re-running is safe (upsert by chunk_id)."""
        if not chunks:
            return

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            self._collection.upsert(
                ids=[c.chunk_id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[c.metadata for c in batch],
            )
        logger.info("Upserted %d chunks into '%s'", len(chunks), self.settings.chroma_collection_name)

    def delete_by_source_ids(self, source_ids: list[str]) -> None:
        """Delete all chunks belonging to given source documents (for re-sync)."""
        if not source_ids:
            return
        self._collection.delete(where={"source_id": {"$in": source_ids}})

    def clear(self) -> None:
        self._client.delete_collection(self.settings.chroma_collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.settings.chroma_collection_name,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    # -- Read path --------------------------------------------------------

    def query(self, query_text: str, top_k: int | None = None, where: dict[str, Any] | None = None):
        n_results = top_k or self.settings.retrieval_top_k
        results = self._collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where,
        )
        return results

    def count(self) -> int:
        return self._collection.count()
