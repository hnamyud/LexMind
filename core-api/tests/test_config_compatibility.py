from app.core.config import get_settings


def _settings(monkeypatch, **values):
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


def test_canonical_environment_values_override_legacy_aliases(monkeypatch):
    settings = _settings(
        monkeypatch,
        APP_ENV="production",
        NODE_ENV="development",
        CORE_API_PORT="8080",
        PORT="9000",
        AI_SERVICE_URL="http://canonical-ai:8001",
        LEXMIND_AI_SERVICE_URL="http://legacy-ai:8001",
    )

    assert settings.is_production
    assert settings.core_api_port == 8080
    assert settings.ai_base_url == "http://canonical-ai:8001"


def test_legacy_environment_aliases_remain_supported(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("CORE_API_PORT", raising=False)
    monkeypatch.delenv("AI_SERVICE_URL", raising=False)
    settings = _settings(
        monkeypatch,
        NODE_ENV="production",
        PORT="9090",
        LEXMIND_AI_SERVICE_URL="http://legacy-ai:8001",
    )

    assert settings.is_production
    assert settings.core_api_port == 9090
    assert settings.ai_base_url == "http://legacy-ai:8001"
