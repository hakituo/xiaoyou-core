import asyncio
from unittest.mock import AsyncMock

from starlette.requests import Request

from core.middleware import security


def _request(
    *,
    peer: str,
    path: str = "/api/v1/message",
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": raw_headers,
            "client": (peer, 43210),
            "server": ("127.0.0.1", 8000),
        }
    )


def test_forwarded_loopback_does_not_change_remote_peer_trust():
    request = _request(
        peer="203.0.113.10",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert security.get_client_ip(request) == "127.0.0.1"
    assert security.get_peer_ip(request) == "203.0.113.10"
    assert security.is_loopback_peer(request) is False


def test_real_ipv4_and_ipv6_loopback_peers_remain_recognized():
    assert security.is_loopback_peer(_request(peer="127.0.0.1")) is True
    assert security.is_loopback_peer(_request(peer="::1")) is True
    assert security.is_loopback_peer(_request(peer="203.0.113.10")) is False


def test_forged_forwarded_loopback_cannot_bypass_token(monkeypatch):
    request = _request(
        peer="203.0.113.10",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    call_next = AsyncMock()
    monkeypatch.setattr(security, "get_required_access_token", lambda: "secret")
    monkeypatch.setattr(security, "is_loopback_auth_bypass_enabled", lambda: True)

    response = asyncio.run(security.security_middleware(request, call_next))

    assert response.status_code == 401
    call_next.assert_not_awaited()


def test_loopback_bypass_can_be_disabled_behind_reverse_proxy(monkeypatch):
    request = _request(peer="127.0.0.1")
    call_next = AsyncMock()
    monkeypatch.setattr(security, "get_required_access_token", lambda: "secret")
    monkeypatch.setattr(security, "is_loopback_auth_bypass_enabled", lambda: False)

    response = asyncio.run(security.security_middleware(request, call_next))

    assert response.status_code == 401
    call_next.assert_not_awaited()
