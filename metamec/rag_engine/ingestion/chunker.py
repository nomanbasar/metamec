"""
Splits WPDocument content into overlapping chunks suitable for embedding.

Simple character-based recursive splitter — no extra heavy dependency
(e.g. langchain) required. Swap in a smarter splitter later if needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .wp_client import WPDocument

_SEPARATORS = ["\n\n", "\n", ". ", " "]


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict


def _hard_split(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Last-resort character-level split, used when a single token (e.g. a long
    URL or unbroken string) exceeds chunk_size on its own, or when the
    separator-based split below fails to make progress. Guarantees forward
    progress every step, so it always terminates.
    """
    if not text:
        return []
    step = max(chunk_size - chunk_overlap, 1)  # always positive -> always progresses
    pieces = []
    i = 0
    while i < len(text):
        pieces.append(text[i : i + chunk_size])
        i += step
    return pieces


def _split_text(text: str, chunk_size: int, chunk_overlap: int, depth: int = 0) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    # Safety valve: if we've recursed unreasonably deep, something about this
    # text/overlap combination isn't converging via separator splitting.
    # Force a hard split rather than let it recurse forever.
    if depth > 20:
        return _hard_split(text, chunk_size, chunk_overlap)

    for sep in _SEPARATORS:
        if sep in text:
            parts = text.split(sep)
            break
    else:
        # No separator found at all (e.g. one giant unbroken token) -> hard split
        return _hard_split(text, chunk_size, chunk_overlap)

    chunks: list[str] = []
    current = ""
    for part in parts:
        # A single part longer than chunk_size can never fit alone —
        # flush what we have, hard-split this oversized part on its own,
        # and continue.
        if len(part) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(part, chunk_size, chunk_overlap))
            continue

        candidate = f"{current}{sep}{part}" if current else part
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Start new chunk, carrying overlap from the tail of the previous one
            overlap_text = current[-chunk_overlap:] if chunk_overlap else ""
            current = f"{overlap_text}{sep}{part}" if overlap_text else part
    if current:
        chunks.append(current)

    # Recursively split any chunk still too large. When chunk_overlap is close
    # to chunk_size, the overlap carried into a new chunk can outweigh the
    # progress made by removing a part — producing a chunk that's the same
    # size (or larger) than what went in, which would recurse forever. Detect
    # that non-shrinking case and force a hard split instead of recursing.
    final: list[str] = []
    for c in chunks:
        if len(c) > chunk_size:
            if len(c) >= len(text):
                final.extend(_hard_split(c, chunk_size, chunk_overlap))
            else:
                final.extend(_split_text(c, chunk_size, chunk_overlap, depth + 1))
        else:
            final.append(c)
    return final


def chunk_document(doc: WPDocument, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    text = doc.content_text
    pieces = _split_text(text, chunk_size, chunk_overlap)

    chunks: list[Chunk] = []
    for i, piece in enumerate(pieces):
        chunks.append(
            Chunk(
                chunk_id=f"{doc.source_id}-chunk-{i}",
                text=piece,
                metadata={
                    "source_id": doc.source_id,
                    "post_type": doc.post_type,
                    "title": doc.title,
                    "url": doc.url,
                    "modified_at": doc.modified_at,
                    "chunk_index": i,
                },
            )
        )
    return chunks