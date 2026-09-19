"""Ollama-backed RAG service with pgvector similarity search.

Embeddings are requested directly from the Ollama REST API via httpx and
stored/queried in PostgreSQL through pgvector; no orchestration framework is
used.
"""

from __future__ import annotations

from typing import Optional

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.db_models import Embedding


import logging

logger = logging.getLogger(__name__)


class RAGService:
    """Manages document embeddings and semantic similarity retrieval.

    This service handles communication with the Ollama embedding API and
    performs vector similarity searches using pgvector in PostgreSQL.
    """

    def __init__(self) -> None:
        """Initializes the RAGService with Ollama configuration settings."""
        self._embed_url = f"{settings.ollama_base_url}/api/embeddings"
        self._embed_model = settings.embed_model

    # ── Embedding ────────────────────────────────────────────────────────────

    async def embed_text(self, text_content: str) -> list[float]:
        """Generate an embedding vector for the given text using Ollama.

        Args:
            text_content: The text string to be converted into a vector embedding.

        Returns:
            A 768-dimensional float list representing the semantic embedding of the text.

        Raises:
            RuntimeError: If the embedding request to Ollama fails or returns an error.
        """
        try:
            async with httpx.AsyncClient(timeout=1020.0) as client:
                resp = await client.post(
                    self._embed_url,
                    json={"model": self._embed_model, "prompt": text_content},
                )
                resp.raise_for_status()
                return resp.json()["embedding"]
        except Exception as exc:
            raise RuntimeError(f"Embedding failed: {exc}") from exc

    async def store_embedding(
        self,
        source_type: str,
        source_id: Optional[int],
        content: str,
        db: AsyncSession,
    ) -> None:
        """Embed and persist a text chunk to the embeddings table.

        Args:
            source_type: The category of the source (e.g., 'lab_result', 'bp_summary').
            source_id: The primary key ID of the source record.
            content: The actual text content to be embedded and stored.
            db: The asynchronous SQLAlchemy database session.
        """
        vector = await self.embed_text(content)
        emb = Embedding(
            source_type=source_type,
            source_id=source_id,
            content=content,
            embedding=vector,
        )
        db.add(emb)
        await db.commit()

    # ── Retrieval ────────────────────────────────────────────────────────────

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        threshold: float = settings.rag_similarity_threshold,
        db: AsyncSession = None,
        source_types: Optional[list[str]] = None,
    ) -> list[str]:
        """Semantic similarity search using pgvector cosine distance.

        Args:
            query: The user's question or search topic.
            limit: The maximum number of results to return. Defaults to 5.
            threshold: The minimum similarity score (1 - cosine distance).
                Defaults to ``settings.rag_similarity_threshold`` (0.75).
            db: The asynchronous SQLAlchemy database session.
            source_types: Optional allow-list of ``Embedding.source_type`` values.
                When provided, only chunks whose source type is in the list are
                returned. When ``None``, no source-type filtering is applied.

        Returns:
            A list of matching content strings, ordered by relevance.
        """
        if db is None:
            return []

        try:
            vector = await self.embed_text(query)
            # pgvector operator <=> is cosine distance
            stmt = select(Embedding.content).where(
                # only return chunks closer than threshold
                (1 - Embedding.embedding.op("<=>")(vector)) >= threshold
            )
            if source_types:
                stmt = stmt.where(Embedding.source_type.in_(source_types))
            stmt = (
                stmt.order_by(Embedding.embedding.op("<=>")(vector))
                .limit(limit)
            )
            result = await db.execute(stmt)
            return [row[0] for row in result.fetchall()]
        except Exception as exc:
            logger.error(f"Similarity search failed: {exc}")
            return []

    # ── Context building ─────────────────────────────────────────────────────

    async def build_context(
        self,
        query: str,
        user_profile: Optional[object],
        db: AsyncSession,
    ) -> str:
        """Assemble a context string from semantically similar stored records.

        The returned content comes exclusively from the ``embeddings`` table,
        which currently stores only the user's own previously ingested records
        (``lab_result``, ``samsung_summary``, ``family_history``). No external
        medical literature (e.g. MedlinePlus or USPSTF guideline text) is
        stored, so this method does NOT return external reference material and
        must not be presented as such.

        This method also performs no deduplication against data already
        injected by the chat router; the same underlying record may appear both
        in the structured summaries and in this context.

        Args:
            query: The user's input message.
            user_profile: The UserProfile ORM object or None.
            db: The asynchronous SQLAlchemy database session.

        Returns:
            A formatted context string containing relevant matches from the
            vector store, or an empty string when nothing is found.
        """
        sections: list[str] = []

        # 1. Semantic search for relevant matches
        similar = await self.similarity_search(query, limit=5, db=db)
        if similar:
            sections.append("=== Relevant Health Context ===")
            sections.extend(similar)

        return "\n".join(sections)


rag_service = RAGService()
