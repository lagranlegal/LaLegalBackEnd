from unittest.mock import patch

from app.core.observability import init_sentry, scrub_event
from app.core.settings import Settings


def _settings(dsn: str) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
        supabase_url="http://127.0.0.1:54321",
        supabase_jwks_url="http://127.0.0.1:54321/auth/v1/.well-known/jwks.json",
        sentry_dsn=dsn,
    )


def test_without_dsn_sentry_is_not_initialized() -> None:
    with patch("sentry_sdk.init") as sentry_init:
        assert init_sentry(_settings("")) is False
        assert init_sentry(_settings("   ")) is False
    sentry_init.assert_not_called()


def test_with_dsn_sentry_is_initialized_without_pii() -> None:
    with patch("sentry_sdk.init") as sentry_init:
        assert init_sentry(_settings("https://key@o0.ingest.sentry.io/0")) is True
    kwargs = sentry_init.call_args.kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["before_send"] is scrub_event
    assert kwargs["max_request_body_size"] == "never"


def test_scrub_event_removes_credentials_and_body() -> None:
    event = {
        "request": {
            "url": "https://api.example.com/api/v1/customers",
            "headers": {
                "Authorization": "Bearer abc",
                "Cookie": "sb=1",
                "Content-Type": "application/json",
            },
            "data": {"document_number": "123"},
            "cookies": {"sb": "1"},
        }
    }

    scrubbed = scrub_event(event)

    assert scrubbed["request"]["headers"] == {"Content-Type": "application/json"}
    assert "data" not in scrubbed["request"]
    assert "cookies" not in scrubbed["request"]
    assert scrubbed["request"]["url"].endswith("/customers")
