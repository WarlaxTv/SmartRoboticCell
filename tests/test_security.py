from __future__ import annotations

from datetime import timedelta

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
    [("ope123", True), ("maint123", True), ("wrong", False)],
)
def test_verify_password_demo_mode(
    password: str,
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SRC_ALLOW_INSECURE_DEMO_AUTH", "1")
    assert security.verify_password(password, "ignored") is expected
