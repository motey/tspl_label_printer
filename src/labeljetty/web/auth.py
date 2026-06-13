from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from fastapi import HTTPException, status, Depends

from labeljetty.config import Config
from labeljetty.core.logging import get_logger


config = Config()
log = get_logger()

# Security scheme
security = HTTPBearer(auto_error=False)


async def verify_token(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
) -> bool:
    """
    Verify the access token if ACCESS_TOKEN is configured.
    If ACCESS_TOKEN is None, the endpoint is public and no verification is performed.
    """
    # If no token is configured, allow public access
    if config.API_ACCESS_TOKEN is None:
        return True

    # If token is configured but not provided, raise error
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify the token
    if credentials.credentials != config.API_ACCESS_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid access token",
        )
    return True


async def require_access(
    authorized: Annotated[bool, Depends(verify_token)],
) -> bool:
    """Central authorization seam for **every** endpoint (API and web UI).

    Today this simply delegates to the single optional bearer-token check
    (:func:`verify_token`). It exists as the one place where the planned
    multi-mode auth (``AUTH_MODE`` = open / token / login, multi-token,
    env-configured users with hashed passwords, and session cookies) will be
    implemented in a dedicated follow-up session — so adding it then will not
    touch any route signatures.

    TODO(auth): implement open / multi-token / login-session resolution here.
    """
    return authorized
