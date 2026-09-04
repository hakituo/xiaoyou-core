import asyncio

from starlette.requests import Request

from core.middleware import security


def _request(*, peer: str, headers=None, path: str = "/api/test") -> Request:
    raw_headers = [
        (str(key).lower().encode("latin-1"), str(value).encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "client": (peer, 12345),
        "server": ("127.0.0.1", 8000),
    }
    return Request(scope)


def test_forwarded_for_cannot_turn_remote_peer_into_loopback():
    request = _request(
        peer="203.0.113.10",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert security.get_client_ip(request) == "127.0.0.1"
    assert security.get_peer_ip(request) == "203.0.113.10"
    assert security.is_loopback_peer(request) is False


def test_actual_loopback_peer_is_recognized():
    assert security.is_loopback_peer(_request(peer="127.0.0.1")) is True
    assert security.is_loopback_peer(_request(peer="::1")) is True


def test_remote_spoofed_loopback_still_requires_token(monkeypatch):
    monkeypatch.setattr(security, "get_required_access_token", lambda: "secret")
    request = _request(
        peer="203.0.113.10",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    called = False

    async def call_next(_request):
        nonlocal called
        called = True
        raise AssertionError("unauthenticated request must not reach protected handler")

    response = asyncio.run(security.security_middleware(request, call_next))

    assert response.status_code == 401
    assert called is False
