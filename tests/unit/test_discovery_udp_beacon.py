#!/usr/bin/env python3
"""`core.services.discovery.udp_beacon` 信标载荷的单元测试。

载荷格式是前后端之间的**线上契约**（客户端 `ServerDiscoveryManager.tryDiscoverByUdp` 按
`|` 分段解析），改动必须两侧同步，所以把两种形态钉住：有组网地址三段、没有两段。
"""

from __future__ import annotations

import pytest

from core.services.discovery.udp_beacon import BROADCAST_MAGIC, UDPBeaconService


@pytest.fixture()
def beacon() -> UDPBeaconService:
    return UDPBeaconService(http_port=8000)


class TestBuildMessage:
    """信标载荷拼装。"""

    def test_includes_vpn_segment_when_available(
        self, beacon: UDPBeaconService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "core.services.discovery.udp_beacon.find_vpn_address",
            lambda: "100.64.0.1",
        )
        assert beacon.build_message("192.0.2.1") == (
            f"{BROADCAST_MAGIC}|http://192.0.2.1:8000|http://100.64.0.1:8000"
        )

    def test_omits_vpn_segment_when_absent(
        self, beacon: UDPBeaconService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 后端没启用组网时必须整段省略：客户端据此区分「后端没有组网入口」与「信标没发全」
        monkeypatch.setattr(
            "core.services.discovery.udp_beacon.find_vpn_address", lambda: None
        )
        assert beacon.build_message("192.0.2.1") == (
            f"{BROADCAST_MAGIC}|http://192.0.2.1:8000"
        )

    def test_uses_configured_http_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "core.services.discovery.udp_beacon.find_vpn_address", lambda: None
        )
        custom = UDPBeaconService(http_port=9001)
        assert custom.build_message("10.0.0.5") == f"{BROADCAST_MAGIC}|http://10.0.0.5:9001"

    def test_vpn_address_is_not_cached(
        self, beacon: UDPBeaconService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 组网地址会随节点重新登录变化，缓存住会让客户端一直拿失效地址去探测
        current = {"value": "100.64.0.1"}
        monkeypatch.setattr(
            "core.services.discovery.udp_beacon.find_vpn_address",
            lambda: current["value"],
        )
        assert "100.64.0.1" in beacon.build_message("192.0.2.1")
        current["value"] = "100.64.0.1"
        assert "100.64.0.1" in beacon.build_message("192.0.2.1")
