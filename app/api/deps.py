"""Bearer-token auth for the JSON API.

The API ignores the session cookie entirely — write endpoints require a
bearer token verified against ``DATA_DIR/api_tokens.json`` (see
``app.auth.tokens``), independent of the web login gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import tokens as auth_tokens
from app.web.deps import get_tokens_path

_bearer = HTTPBearer(auto_error=False)


def require_token(
    tokens_path: Annotated[Path, Depends(get_tokens_path)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> str:
    """Return the token's name, or raise a 401 with a WWW-Authenticate header."""
    if credentials is not None:
        name = auth_tokens.verify_token(tokens_path, credentials.credentials)
        if name is not None:
            return name
    raise HTTPException(
        status_code=401,
        detail="Missing or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
