from fastapi import Request

from app.api.auth import _canonical_google_login_url
from app.core.config import get_settings


def _request(scheme: str, host: str, port: int) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": scheme,
            "path": "/auth/google/login",
            "raw_path": b"/auth/google/login",
            "query_string": b"",
            "headers": [(b"host", f"{host}:{port}".encode())],
            "server": (host, port),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
        }
    )


def test_production_reverse_proxy_origin_does_not_self_redirect():
    settings = get_settings().model_copy(
        update={
            "app_env": "production",
            "google_redirect_uri": "https://lex-mind.duckdns.org/auth/google/callback",
        }
    )
    request = _request("http", "core-api", 8080)

    assert _canonical_google_login_url(request, settings) is None


def test_development_normalizes_127_to_localhost():
    settings = get_settings().model_copy(
        update={
            "app_env": "development",
            "google_redirect_uri": "http://localhost:8080/auth/google/callback",
        }
    )
    request = _request("http", "127.0.0.1", 8080)

    assert (
        _canonical_google_login_url(request, settings)
        == "http://localhost:8080/auth/google/login"
    )
