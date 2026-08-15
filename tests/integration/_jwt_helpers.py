"""Helpers compartidos para fabricar JWTs firmados con una llave RSA de
prueba y un JWKS falso (monkeypatch de `app.core.security.get_jwk_client`).
No es un módulo de test — pytest no lo colecciona (no matchea test_*.py).
"""

from datetime import UTC, datetime, timedelta
from typing import Any


class FakeSigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class FakeJwkClient:
    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> FakeSigningKey:
        return FakeSigningKey(self._public_key)


def make_token(private_pem: str, **overrides: Any) -> str:
    import jwt

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": overrides.pop("sub", None) or "00000000-0000-0000-0000-000000000000",
        "aud": "authenticated",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, private_pem, algorithm="RS256")
