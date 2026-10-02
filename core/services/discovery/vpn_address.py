#!/usr/bin/env python3
"""组网地址探测。

找出本机在点对点组网网段（Tailscale / WireGuard 常用的 CGNAT ``100.64.0.0/10``）里的
IPv4 地址，供 UDP 信标一并广播给客户端。

为什么单独一个模块：「局域网 IP」和「组网地址」的取法完全不同 —— 前者是默认路由的出口地址
（往外连一次就能问出来），后者在**另一张虚拟网卡**上，只能靠枚举网卡拿到。两者混在一起写，
很容易顺手用取出口地址的办法去取组网地址，结果永远拿不到。
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Iterator, Optional

import psutil

from core.utils.logger import get_logger

logger = get_logger(__name__)

#: 点对点组网网段（CGNAT）。Tailscale / WireGuard 默认从这里分配地址。
VPN_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def is_vpn_address(candidate: str) -> bool:
    """判断字符串是不是组网网段里的 IPv4 地址。

    与「私网地址」判据必须分开：``100.64.0.0/10`` 外观像内网，但它在蜂窝网络下是可达的，
    客户端据此把它归成独立的「组网通道」而不是局域网候选。
    """
    try:
        return ipaddress.ip_address(candidate.strip()) in VPN_NETWORK
    except ValueError:
        return False


def find_vpn_address() -> Optional[str]:
    """返回本机的组网地址；没装 / 没连组网时返回 None。

    只认 IPv4：客户端槽位存的是 ``http://<ip>:<port>``，IPv6 还要额外加方括号处理，
    而 Tailscale 的 CGNAT 段本来就是 IPv4。
    """
    for name, address in iter_ipv4_addresses():
        if is_vpn_address(address):
            logger.debug(f"发现组网地址 {address}（网卡 {name}）")
            return address
    return None


def iter_ipv4_addresses() -> Iterator[tuple[str, str]]:
    """枚举本机所有网卡的 IPv4 地址，产出 ``(网卡名, 地址)``。

    用 psutil 而不是 ``socket.getaddrinfo(socket.gethostname())``：后者在 Linux 上通常只返回
    ``/etc/hosts`` 里那一条，枚举不到组网网卡。枚举失败时产出空序列而不是抛异常 ——
    组网地址是可选能力，探测不到不该影响信标广播本身。
    """
    try:
        interfaces = psutil.net_if_addrs()
    except Exception as exc:  # pragma: no cover - 依赖系统调用，异常分支难构造
        logger.warning(f"枚举网卡失败，组网地址探测跳过: {exc}")
        return

    for name, entries in interfaces.items():
        for entry in entries:
            if entry.family != socket.AF_INET:
                continue
            # 去掉链路本地地址可能带的 %scope 后缀（如 fe80::1%eth0 的 IPv4 对应形态）
            yield name, entry.address.split("%", 1)[0]
