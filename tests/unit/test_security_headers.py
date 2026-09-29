from fastapi.testclient import TestClient

from app.core.security_headers import HSTS_VALUE, hsts_enabled
from app.core.settings import Settings
from app.main import create_app


def _client(environment: str) -> TestClient:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
        supabase_url="http://127.0.0.1:54321",
        supabase_jwks_url="http://127.0.0.1:54321/auth/v1/.well-known/jwks.json",
        environment=environment,
    )
    return TestClient(create_app(settings))


def test_every_response_carries_the_base_security_headers() -> None:
    response = _client("production").get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Strict-Transport-Security"] == HSTS_VALUE


def test_error_responses_also_carry_the_headers() -> None:
    response = _client("production").get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_hsts_is_sent_in_every_deployed_environment() -> None:
    assert hsts_enabled("production", fly_app_name="") is True
    assert hsts_enabled("staging", fly_app_name="") is True
    # El dev remoto dice "dev" pero corre en Fly, detrás de HTTPS.
    assert hsts_enabled("dev", fly_app_name="compraventa-backend-dev") is True


def test_hsts_is_omitted_in_local_development() -> None:
    assert hsts_enabled("dev", fly_app_name="") is False
