from app.common.cors import LOCAL_DEV_ORIGINS, VERCEL_PREVIEW_REGEX, build_cors_config


def test_dev_adds_localhost_and_vercel_preview_regex() -> None:
    origins, regex = build_cors_config(cors_allow_origins="", environment="dev")

    assert set(LOCAL_DEV_ORIGINS).issubset(origins)
    assert regex == VERCEL_PREVIEW_REGEX


def test_dev_merges_explicit_origins_with_localhost_without_duplicates() -> None:
    origins, _ = build_cors_config(
        cors_allow_origins="http://localhost:5173,https://staging.example.com",
        environment="dev",
    )

    assert origins.count("http://localhost:5173") == 1
    assert "https://staging.example.com" in origins


def test_production_only_allows_explicit_origins_no_regex() -> None:
    origins, regex = build_cors_config(
        cors_allow_origins="https://app.lagranlegal.com", environment="production"
    )

    assert origins == ["https://app.lagranlegal.com"]
    assert regex is None
    for local_origin in LOCAL_DEV_ORIGINS:
        assert local_origin not in origins


def test_production_without_configured_origins_allows_nothing() -> None:
    origins, regex = build_cors_config(cors_allow_origins="", environment="production")

    assert origins == []
    assert regex is None


def test_blank_and_whitespace_origins_are_ignored() -> None:
    origins, _ = build_cors_config(
        cors_allow_origins=" , https://app.lagranlegal.com , ,", environment="production"
    )

    assert origins == ["https://app.lagranlegal.com"]
