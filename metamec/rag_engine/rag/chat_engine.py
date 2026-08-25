"""
RAG chat engine: retrieves relevant chunks from ChromaDB and generates
a grounded answer with OpenAI's chat completion API.

This is the main class the Django backend should import and call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from openai import OpenAI

from ..config import Settings, settings as default_settings
from ..vectorstore.store import VectorStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the AI assistant for Dragon Finance, a UK secured loan broker.
Answer the user's question using ONLY the context provided below, which is
sourced from the official Dragon Finance website.

Rules:
- If the context does not contain enough information to answer confidently, \
say so plainly and suggest the user contact Dragon Finance directly — do not guess.
- Never invent rates, fees, eligibility criteria, or figures that are not in the context.
- Be concise and clear. Use plain English, avoid jargon where possible.
- Do not provide personalised financial advice; present general information only.

Context:
{context}
"""


@dataclass
class RetrievedSource:
    title: str
    url: str
    text: str


@dataclass
class RAGResponse:
    answer: str
    sources: list[RetrievedSource] = field(default_factory=list)


class RAGChatEngine:
    def __init__(self, cfg: Settings = default_settings, store: VectorStore | None = None):
        self.cfg = cfg
        self.store = store or VectorStore(cfg)
        self.client = OpenAI(api_key=cfg.openai_api_key)

    def _retrieve(self, query: str, top_k: int | None = None) -> list[RetrievedSource]:
        results = self.store.query(query, top_k=top_k)

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        sources: list[RetrievedSource] = []
        for text, meta in zip(documents, metadatas):
            sources.append(
                RetrievedSource(
                    title=meta.get("title", ""),
                    url=meta.get("url", ""),
                    text=text,
                )
            )
        return sources

    def _build_context(self, sources: list[RetrievedSource]) -> str:
        if not sources:
            return "No relevant content found."
        blocks = []
        for s in sources:
            blocks.append(f"[Source: {s.title} ({s.url})]\n{s.text}")
        return "\n\n---\n\n".join(blocks)

    def answer(
        self,
        query: str,
        chat_history: list[dict] | None = None,
        top_k: int | None = None,
    ) -> RAGResponse:
        """
        chat_history: optional list of prior turns, each
            {"role": "user"|"assistant", "content": "..."}
        for multi-turn conversations. Pass None/[] for a single-shot query.
        """
        sources = self._retrieve(query, top_k=top_k)
        context = self._build_context(sources)

        messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context)}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": query})

        completion = self.client.chat.completions.create(
            model=self.cfg.openai_chat_model,
            messages=messages,
            temperature=0.2,
        )

        answer_text = completion.choices[0].message.content or ""
        return RAGResponse(answer=answer_text, sources=sources)
