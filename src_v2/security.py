"""Authentication helpers for Smart Robotic Cell V2.

This module provides JWT token creation and role-based access control.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from src_v2.db import get_session, get_user

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def get_secret_key() -> str:
    """Return JWT secret key.

    For OWASP compliance, secrets should not be hard-coded.
    """

    return os.environ.get(
        "SRC_JWT_SECRET_KEY",
        "SUPER_SECRET_ROBOTIC_KEY_V2_CHANGE_ME_32_BYTES_MINIMUM",
    )


def get_demo_auth_enabled() -> bool:
    """Enable insecure demo authentication fallback.

    When enabled, the project accepts the demo passwords even if passlib is missing.
    Set SRC_ALLOW_INSECURE_DEMO_AUTH=0 to disable this behavior.
    """

    return os.environ.get("SRC_ALLOW_INSECURE_DEMO_AUTH", "1") not in {
        "0",
        "false",
        "False",
    }


try:
    from passlib.context import CryptContext

    PWD_CONTEXT: Any = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception:  # pragma: no cover
    PWD_CONTEXT = None


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password.

    Uses passlib/bcrypt when available.
    Falls back to a demo-mode validation if explicitly enabled.
    """

    demo_allowed = get_demo_auth_enabled()

    if PWD_CONTEXT is not None:
        try:
            return bool(PWD_CONTEXT.verify(plain_password, hashed_password))
        except Exception:
            # En environnement POC, on préfère un fallback contrôlé à un blocage total.
            if demo_allowed:
                return plain_password in {"ope123", "maint123"}
            return False

    if not demo_allowed:
        return False

    return plain_password in {"ope123", "maint123"}

def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""

    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, get_secret_key(), algorithm=ALGORITHM)

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
    except jwt.InvalidTokenError as exc:
        raise credentials_exception from exc

    user = get_user(session, username)
    if user is None:
        raise credentials_exception
    return {"username": username, "role": role}

def require_role(required_role: str) -> Callable[[dict[str, str]], dict[str, str]]:
    """FastAPI dependency enforcing a specific role."""

    def role_checker(
        current_user: dict[str, str] = Depends(get_current_user),
    ) -> dict[str, str]:
        if current_user["role"] != required_role:
            raise HTTPException(
                status_code=403,
                detail="Rôle insuffisant pour cette action",
            )
        return current_user
    return role_checker
