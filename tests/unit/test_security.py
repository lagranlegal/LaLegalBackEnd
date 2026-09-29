from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core import security
from app.core.errors import UnauthorizedError
from app.core.settings import get_settings


class _FakeSigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class _FakeJwkClient:
    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> _FakeSigningKey:
        return _FakeSigningKey(self._public_key)


def _make_token(private_pem: str, **overrides: object) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "iss": get_settings().jwt_issuer,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "company_id": str(uuid4()),
        "role_id": str(uuid4()),
    }
    payload.update(overrides)
    return jwt.encode(payload, private_pem, algorithm="RS256")


def test_decode_token_valid(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> None:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(public_key))

    claims = security.decode_token(_make_token(private_pem))

    assert claims.sub is not None
    assert claims.company_id is not None
    assert claims.role_id is not None


def test_decode_token_expired(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> None:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(public_key))

    expired = _make_token(private_pem, exp=datetime.now(UTC) - timedelta(minutes=1))
    with pytest.raises(UnauthorizedError):
        security.decode_token(expired)


def test_decode_token_wrong_audience(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> None:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(public_key))

    token = _make_token(private_pem, aud="other-audience")
    with pytest.raises(UnauthorizedError):
        security.decode_token(token)


def test_decode_token_bad_signature(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keypair: tuple[str, object],
    rsa_keypair_other: tuple[str, object],
) -> None:
    private_pem, _ = rsa_keypair
    _, other_public_key = rsa_keypair_other
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(other_public_key))

    token = _make_token(private_pem)
    with pytest.raises(UnauthorizedError):
        security.decode_token(token)


async def test_get_verified_claims_rejects_missing_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> None:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(public_key))

    token = _make_token(private_pem, company_id=None, role_id=None)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(UnauthorizedError):
        await security.get_verified_claims(credentials)


async def test_get_verified_claims_rejects_missing_header() -> None:
    with pytest.raises(UnauthorizedError):
        await security.get_verified_claims(None)


def test_decode_token_rejects_token_from_another_issuer(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> None:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(public_key))

    other = _make_token(private_pem, iss="https://otro-proyecto.supabase.co/auth/v1")
    with pytest.raises(UnauthorizedError):
        security.decode_token(other)


def test_decode_token_requires_issuer(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> None:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(public_key))

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_pem,
        algorithm="RS256",
    )
    with pytest.raises(UnauthorizedError):
        security.decode_token(token)


def test_jwt_issuer_is_the_project_auth_url() -> None:
    assert get_settings().jwt_issuer == f"{get_settings().supabase_url.rstrip('/')}/auth/v1"
