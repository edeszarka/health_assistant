"""LangChain + Ollama RAG service with pgvector similarity search."""

from __future__ import annotations

from typing import Optional

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.db_models import Embedding


class RAGService:
    """Manages document embeddings and semantic similarity retrieval."""

    def __init__(self) -> None:
        self._embed_url = f"{settings.ollama_base_url}/api/embeddings"
        self._embed_model = settings.embed_model

    # ── Embedding ────────────────────────────────────────────────────────────

    async def embed_text(self, text_content: str) -> list[float]:
        """Generate an embedding vector for the given text using Ollama.

        Args:
            text_content: The text to embed.

        Returns:
            768-dimensional float list.
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
            source_type: One of lab_result/samsung_summary/family_history/guideline/bp_summary.
            source_id: Foreign-key id to the source row (nullable).
            content: The text to embed.
            db: Async DB session.
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
            query: The user's question or topic.
            limit: Maximum number of results to return.
            db: Async DB session.

        Returns:
            List of matching content strings (most relevant first).
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
            query: The user's message.
            user_profile: UserProfile ORM row (or None).
            db: Async DB session.

        Returns:
            Formatted context string containing relevant matches.
        """
        sections: list[str] = []

        # 1. Semantic search for relevant matches
        similar = await self.similarity_search(query, limit=5, db=db)
        if similar:
            sections.append("=== Relevant Health Context ===")
            sections.extend(similar)

        return "\n".join(sections)


rag_service = RAGService()
