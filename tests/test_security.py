from __future__ import annotations

from datetime import timedelta

import bcrypt
import pytest

from src_v2 import security


def test_create_access_token_roundtrip() -> None:
    token = security.create_access_token(
        {"sub": "jean_ope", "role": "OPERATEUR"}, timedelta(minutes=5)
    )
    payload = security.jwt.decode(
        token,
        security.get_secret_key(),
        algorithms=[security.ALGORITHM],
    )
    assert payload["sub"] == "jean_ope"
    assert payload["role"] == "OPERATEUR"
    assert "exp" in payload


@pytest.mark.parametrize(
    ("password", "expected"),
    [("ope123", True), ("wrong", False)],
)
def test_verify_password_real_bcrypt(password: str, expected: bool) -> None:
    """verify_password vérifie réellement le hash bcrypt (correctif INC-V2-012).

    Remplace l'ancien test_verify_password_demo_mode : celui-ci passait un
    hash factice ("ignored") et ne testait donc que le contournement en
    clair supprimé par le correctif, pas une vraie vérification bcrypt.
    """
    hashed = bcrypt.hashpw(b"ope123", bcrypt.gensalt()).decode("utf-8")
    assert security.verify_password(password, hashed) is expected


def test_verify_password_rejects_malformed_hash() -> None:
    """Un hash invalide/corrompu ne doit jamais faire planter la vérification."""
    assert security.verify_password("ope123", "not-a-real-bcrypt-hash") is False
