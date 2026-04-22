"""FastAPI entry point: lifespan, router registration, health check."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.connection import init_db
from routers import (
    upload,
    chat,
    blood_pressure,
    family_history,
    dashboard,
    recommendations,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB tables and pgvector extension."""
    await init_db()
    yield


app = FastAPI(
    title="Health Assistant API",
    description="Local-first personal health intelligence assistant.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(blood_pressure.router, prefix="/bp", tags=["blood_pressure"])
app.include_router(
    family_history.router, prefix="/family-history", tags=["family_history"]
)
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(
    recommendations.router, prefix="/recommendations", tags=["recommendations"]
)


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Liveness probe."""
    return {"status": "ok"}
