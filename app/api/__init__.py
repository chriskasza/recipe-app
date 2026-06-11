"""JSON API module: REST endpoints under /api/v1, sharing app/db and app/services."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.recipes import router as recipes_router

router = APIRouter()
router.include_router(recipes_router)

__all__ = ["router"]
