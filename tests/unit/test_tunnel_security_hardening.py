from core.middleware.security import (
    MEDIA_AUTH_TTL_SECONDS,
    create_media_auth_cookie,
    get_access_token_from_headers,
    is_protected_path,
    is_trusted_loopback_connection,
    validate_media_auth_cookie,
)


def test_public_sensitive_paths_are_protected():
    protected = [
        "/output",
        "/output/image/uploads/a.png",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/chat",
        "/v1/chat/completions",
    ]
    for path in protected:
        assert is_protected_path(path), path

    assert not is_protected_path("/")
    assert not is_protected_path("/favicon.ico")
    assert not is_protected_path("/static/app.js")


def test_loopback_bypass_rejects_forwarded_external_client():
    assert is_trusted_loopback_connection("127.0.0.1", {})
    assert is_trusted_loopback_connection(
        "127.0.0.1", {"x-forwarded-for": "127.0.0.1"}
    )

    assert not is_trusted_loopback_connection(
        "127.0.0.1", {"cf-connecting-ip": "203.0.113.7"}
    )
    assert not is_trusted_loopback_connection(
        "127.0.0.1", {"x-forwarded-for": "203.0.113.7, 127.0.0.1"}
    )
    assert not is_trusted_loopback_connection("192.0.2.1", {})


def test_access_token_extraction_supports_http_and_ws_shapes():
    assert (
        get_access_token_from_headers({"authorization": "Bearer abc"}) == "abc"
    )
    assert get_access_token_from_headers({"x-internal-token": "xyz"}) == "xyz"
    assert get_access_token_from_headers({}, {"token": "query-token"}) == "query-token"


def test_media_cookie_is_scoped_signature_not_raw_api_token():
    secret = "super-secret-api-token"
    now = 1_700_000_000.0
    cookie = create_media_auth_cookie(secret, now=now)

    assert secret not in cookie
    assert validate_media_auth_cookie(cookie, secret, now=now + 1)
    assert validate_media_auth_cookie(
        cookie, secret, now=now + MEDIA_AUTH_TTL_SECONDS
    )
    assert not validate_media_auth_cookie(
        cookie, secret, now=now + MEDIA_AUTH_TTL_SECONDS + 1
    )
    assert not validate_media_auth_cookie(cookie, "wrong-secret", now=now + 1)
