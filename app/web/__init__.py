"""Web routes and templates. Combined router exported as ``router``."""

from __future__ import annotations

from fastapi import APIRouter

from app.web.crud import router as crud_router
from app.web.library import router as library_router
from app.web.recipe import router as recipe_router

router = APIRouter()
router.include_router(library_router)
router.include_router(recipe_router)
router.include_router(crud_router)
