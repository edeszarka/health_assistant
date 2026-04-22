"""LangChain + Ollama RAG service with pgvector similarity search."""

from __future__ import annotations

from typing import Optional

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.db_models import Embedding


class RAGService:
    """Manages document embeddings and semantic similarity retrieval.

    This service handles communication with the Ollama embedding API and
    performs vector similarity searches using pgvector.
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
            source_id: The primary key ID of the source record in its respective table.
            content: The actual text content to be embedded and stored.
            db: The asynchronous SQLAlchemy database session.

        Returns:
            None.
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
        threshold: float = 0.75,
        db: AsyncSession = None,
    ) -> list[str]:
        """Semantic similarity search using pgvector cosine distance.

        Args:
            query: The user's question or search topic.
            limit: The maximum number of results to return. Defaults to 5.
            threshold: The minimum similarity score (1 - cosine distance). Defaults to 0.75.
            db: The asynchronous SQLAlchemy database session. Defaults to None.

        Returns:
            A list of matching content strings, ordered by relevance (most relevant first).
        """
        if db is None:
            return []

        vector = await self.embed_text(query)
        # pgvector operator <=> is cosine distance
        stmt = (
                select(Embedding.content)
                .where(
                    # only return chunks closer than threshold
                    (1 - Embedding.embedding.op("<=>")(vector)) >= threshold
                )
                .order_by(Embedding.embedding.op("<=>")(vector))
                .limit(limit)
            )
        try:
            result = await db.execute(stmt)
            return [row[0] for row in result.fetchall()]
        except Exception:
            return []

    # ── Context building ─────────────────────────────────────────────────────

    async def build_context(
        self,
        query: str,
        user_profile: Optional[object],
        db: AsyncSession,
    ) -> str:
        """Assemble a rich context string using semantic similarity search.
        
        This method avoids duplicating data already injected by the chat router
        (labs, BP, etc.) and focuses on finding relevant matching content from
        stored embeddings.

        Args:
            query: The user's input message.
            user_profile: The UserProfile ORM object or None.
            db: The asynchronous SQLAlchemy database session.

        Returns:
            A formatted context string containing relevant matches from the vector store.
        """
        sections: list[str] = []

        # 1. Semantic search for relevant matches
        similar = await self.similarity_search(query, limit=5, db=db)
        if similar:
            sections.append("=== Relevant Health Context ===")
            sections.extend(similar)

        return "\n".join(sections)
        sections: list[str] = []

        # 1. Semantic search for relevant matches
        similar = await self.similarity_search(query, limit=5, db=db)
        if similar:
            sections.append("=== Relevant Health Context ===")
            sections.extend(similar)

        return "\n".join(sections)


rag_service = RAGService()
