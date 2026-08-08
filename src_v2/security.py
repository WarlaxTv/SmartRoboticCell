"""Authentication helpers for Smart Robotic Cell V2.

This module provides JWT token creation and role-based access control.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
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


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash.

    Utilise directement la librairie bcrypt plutôt que passlib.CryptContext.
    Correctif définitif de INC-V2-012 (JOURNAL_ERREURS_ET_FIXES_FR.md) :
    passlib 1.7.4 lève AttributeError sur bcrypt >= 4.1 lors de sa détection
    de version de backend (``module 'bcrypt' has no attribute '__about__'``),
    ce qui provoquait un refus de connexion systématique et avait nécessité
    un mode de secours en clair (fallback démo). Cette fonction ne dépend
    plus de passlib et vérifie réellement le hash à chaque appel — il n'y a
    plus de contournement en clair.
    """

    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False

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
