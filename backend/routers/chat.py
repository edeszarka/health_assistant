"""Chat router: RAG-augmented LLM conversation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from models.api_models import ChatRequest, ChatResponse
from models.db_models import UserProfile
from services.rag_service import rag_service
from services.llm_service import llm_service

router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Accept a user message, build RAG context, return LLM reply.

    Args:
        request: ChatRequest with message and conversation history.
        db: Async DB session.

    Returns:
        ChatResponse with reply and source list.
    """
    # Fetch user profile (first row, if exists)
    try:
        result = await db.execute(select(UserProfile).limit(1))
        profile = result.scalar_one_or_none()
    except Exception:
        profile = None

    # Build RAG context
    try:
        context = await rag_service.build_context(request.message, profile, db)
    except Exception as exc:
        context = ""

    # Call LLM
    try:
        reply = await llm_service.chat(
            message=request.message,
            conversation_history=request.conversation_history,
            context=context,
            user_profile=profile,
            query_type=request.query_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}")

    return ChatResponse(reply=reply, sources=[])
