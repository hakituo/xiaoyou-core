#!/usr/bin/env python3
"""`core.services.discovery.vpn_address` 的单元测试。

组网地址探测是「安卓端自动填组网槽位」的数据来源，判错方向的代价不对称：
把普通地址误判成组网地址 → 客户端拿一个不可达地址当组网候选，每次裁决白等 1.5s 超时；
把组网地址漏判 → 槽位永远填不上，用户开着 Tailscale 也只能走公网域名。
所以网段两侧边界都要钉住。
"""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from core.services.discovery.vpn_address import (
    find_vpn_address,
    is_vpn_address,
    iter_ipv4_addresses,
)


def _fake_interfaces(*entries: tuple[str, str, int]) -> dict:
    """把 ``(网卡名, 地址, family)`` 列表拼成 psutil.net_if_addrs() 的返回形状。"""
    interfaces: dict = {}
    for name, address, family in entries:
        interfaces.setdefault(name, []).append(
            SimpleNamespace(family=family, address=address)
        )
    return interfaces


class TestIsVpnAddress:
    """网段判据。"""

    @pytest.mark.parametrize(
        "address",
        [
            "100.64.0.0",  # 网段下界
            "100.127.255.255",  # 网段上界
            "100.64.0.1",  # 实际在用的一个 Tailscale 地址形态
            " 100.64.0.1 ",  # 带空白
        ],
    )
    def test_accepts_cgnat_range(self, address: str) -> None:
        assert is_vpn_address(address) is True

    @pytest.mark.parametrize(
        "address",
        [
            "100.63.255.255",  # 下界外一格
            "100.128.0.0",  # 上界外一格
            "100.0.0.1",
            "192.0.2.1",
            "10.0.0.5",
            "8.8.8.8",
            "2001:db8::1",  # IPv6 不在 IPv4 网段里
            "not-an-ip",
            "",
        ],
    )
    def test_rejects_everything_else(self, address: str) -> None:
        assert is_vpn_address(address) is False


class TestFindVpnAddress:
    """网卡枚举与筛选。"""

    def test_picks_cgnat_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "core.services.discovery.vpn_address.psutil.net_if_addrs",
            lambda: _fake_interfaces(
                ("以太网", "192.0.2.1", socket.AF_INET),
                ("Tailscale", "100.64.0.1", socket.AF_INET),
            ),
        )
        assert find_vpn_address() == "100.64.0.1"

    def test_returns_none_without_cgnat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 没装 / 没连组网时不能瞎猜一个地址，否则客户端会拿它当候选反复白探
        monkeypatch.setattr(
            "core.services.discovery.vpn_address.psutil.net_if_addrs",
            lambda: _fake_interfaces(("以太网", "192.0.2.1", socket.AF_INET)),
        )
        assert find_vpn_address() is None

    def test_ignores_ipv6_only_interface(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 组网网卡也可能只挂了 IPv6，客户端槽位存的是 IPv4 形式，必须跳过
        monkeypatch.setattr(
            "core.services.discovery.vpn_address.psutil.net_if_addrs",
            lambda: _fake_interfaces(("Tailscale", "fd7a:115c:a1e0::1", socket.AF_INET6)),
        )
        assert find_vpn_address() is None

    def test_enumeration_failure_is_not_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 枚举失败是「探测不到」，不是「信标广播失败」——不能把异常抛给调用方
        def _boom() -> dict:
            raise OSError("net_if_addrs 不可用")

        monkeypatch.setattr(
            "core.services.discovery.vpn_address.psutil.net_if_addrs", _boom
        )
        assert find_vpn_address() is None
        assert list(iter_ipv4_addresses()) == []

    def test_strips_scope_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "core.services.discovery.vpn_address.psutil.net_if_addrs",
            lambda: _fake_interfaces(("Tailscale", "100.64.0.1%3", socket.AF_INET)),
        )
        assert find_vpn_address() == "100.64.0.1"
