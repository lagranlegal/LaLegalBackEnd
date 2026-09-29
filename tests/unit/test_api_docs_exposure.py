from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import api_docs_enabled, create_app


def _settings(environment: str) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
        supabase_url="http://127.0.0.1:54321",
        supabase_jwks_url="http://127.0.0.1:54321/auth/v1/.well-known/jwks.json",
        environment=environment,
    )


def test_docs_are_not_served_in_production() -> None:
    client = TestClient(create_app(_settings("production")))

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_docs_are_served_outside_production() -> None:
    client = TestClient(create_app(_settings("dev")))

    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"] == "Prendo API"


def test_api_docs_enabled_only_depends_on_production() -> None:
    assert api_docs_enabled("dev") is True
    assert api_docs_enabled("test") is True
    assert api_docs_enabled("staging") is True
    assert api_docs_enabled("production") is False
