"""
End-to-end ingestion pipeline: WordPress -> chunks -> ChromaDB.

Usage:
    from rag_engine.config import settings
    from rag_engine.ingestion.pipeline import sync_wordpress_content

    sync_wordpress_content(settings)

Or from the CLI:
    python -m rag_engine.ingestion.pipeline
"""

from __future__ import annotations

import logging

from ..config import Settings, settings as default_settings
from ..vectorstore.store import VectorStore
from .chunker import chunk_document
from .wp_client import WordPressClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def sync_wordpress_content(cfg: Settings = default_settings) -> dict:
    """
    Pulls all configured post types from WordPress, chunks them,
    and upserts into ChromaDB. Safe to re-run (idempotent upsert by chunk_id;
    stale chunks from edited/removed pages are cleared first per source).

    Returns a small summary dict, useful for logging / API responses.
    """
    wp_client = WordPressClient(
        base_url=cfg.wp_base_url,
        username=cfg.wp_app_username,
        app_password=cfg.wp_app_password,
    )

    if not wp_client.check_connection():
        raise ConnectionError(
            "Could not connect to WordPress REST API. "
            "Check WP_BASE_URL and Application Password credentials."
        )

    documents = wp_client.fetch_documents(cfg.wp_post_types)

    store = VectorStore(cfg)

    # Clear existing chunks for these sources first, so edited/shortened
    # pages don't leave orphaned stale chunks behind.
    store.delete_by_source_ids([doc.source_id for doc in documents])

    total_chunks = 0
    for doc in documents:
        chunks = chunk_document(doc, cfg.chunk_size, cfg.chunk_overlap)
        store.upsert_chunks(chunks)
        total_chunks += len(chunks)

    summary = {
        "documents_synced": len(documents),
        "chunks_upserted": total_chunks,
        "collection": cfg.chroma_collection_name,
        "collection_count": store.count(),
    }
    logger.info("Sync complete: %s", summary)
    return summary


if __name__ == "__main__":
    sync_wordpress_content()
