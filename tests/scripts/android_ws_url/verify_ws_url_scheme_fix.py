"""验证 WebSocketManager.normalizeWsScheme 修复的正确性。

背景：
  Android 端 WebSocket 反复 403，根因是 buildWsUrl 用了 Kotlin 的
  String.replaceFirst("^http", "ws")，该重载是字面量匹配而非正则，
  "^http" 只匹配字面 5 个字符，不会匹配以 http 开头的字符串。
  导致 "http://host" 没被转换，兜底拼成 "wss://http://host"，
  OkHttp 解析后 host 被当成 "http"，真正的 "//host:port/api/v1/ws"
  全部落入 path，服务端收到畸形 path 匹配不到 /api/v1/ws 路由，
  落入静态文件挂载点被拒（403）。

本脚本用 Python 等价实现旧（有 bug）与新（修复后）两套逻辑，
对比证明：新实现能把 http(s):// 正确转成 ws(s)://，且 host 段
能被 java.net.URI 正确解析（而非落入 path）。

运行：python tests/scripts/android_ws_url/verify_ws_url_scheme_fix.py
"""

from __future__ import annotations

import sys
from urllib.parse import unquote
from dataclasses import dataclass
from typing import Callable


# ---- 旧实现（有 bug，复刻 Kotlin replaceFirst 字面量匹配语义）----

def buggy_normalize_ws_scheme(decoded: str) -> str:
    # Kotlin: decoded.replaceFirst("^https", "wss").replaceFirst("^http", "ws")
    # Kotlin String.replaceFirst(oldValue, newValue) 是字面量匹配，"^https" 只匹配字面 5 字符
    ws_base = decoded.replace("^https", "wss", 1).replace("^http", "ws", 1)
    if not ws_base.startswith("ws://") and not ws_base.startswith("wss://"):
        ws_base = "wss://" + ws_base.removeprefix("//").lstrip("/")
    return ws_base


# ---- 新实现（修复后，复刻 normalizeWsScheme 的 startsWith 分支）----

def fixed_normalize_ws_scheme(decoded: str) -> str:
    if decoded.startswith("https://"):
        return "wss://" + decoded.removeprefix("https://")
    if decoded.startswith("http://"):
        return "ws://" + decoded.removeprefix("http://")
    if decoded.startswith("wss://") or decoded.startswith("ws://"):
        return decoded
    return "wss://" + decoded.removeprefix("//").lstrip("/")


# ---- 复刻 buildWsUrl 的完整流程（含 %3A 解码 + path 拼接）----

def build_ws_url(backend_url: str, normalize: Callable[[str], str]) -> str:
    decoded = unquote(backend_url)
    ws_base = normalize(decoded)
    if "/api/v1" in ws_base:
        if ws_base.endswith("/api/v1") or ws_base.endswith("/api/v1/"):
            ws_url = ws_base.rstrip("/") + "/ws"
        else:
            ws_url = ws_base
    else:
        ws_url = ws_base.rstrip("/") + "/api/v1/ws"
    return ws_url


# ---- 用 urllib 模拟 java.net.URI 解析 host/path ----

def parse_host_path(ws_url: str) -> tuple[str | None, str]:
    """模拟 OkHttp / java.net.URI 对 ws(s):// URL 的解析。

    返回 (host, path)。若 host 为 None 说明 URL 结构畸形（host 被当成 path）。
    """
    from urllib.parse import urlsplit
    parts = urlsplit(ws_url)
    return parts.hostname, parts.path


@dataclass
class Case:
    name: str
    backend_url: str
    expected_host: str
    expected_path: str = "/api/v1/ws"


CASES: list[Case] = [
    Case("http 内网 IP", "http://192.168.31.225:8000", "192.168.31.225"),
    Case("https tunnel", "https://tunnel.example.com", "tunnel.example.com"),
    Case("https tunnel 带端口", "https://tunnel.example.com:8443", "tunnel.example.com"),
    Case("无协议头 IP:port", "192.168.31.225:8000", "192.168.31.225"),
    Case("无协议头域名", "xxx.trycloudflare.com", "xxx.trycloudflare.com"),
    Case("协议相对 //host:port", "//192.168.31.225:8000", "192.168.31.225"),
    Case("%3A 编码的 URL", "http://192.168.31.225%3A8000", "192.168.31.225"),
    Case("ws 前缀保持", "ws://192.168.31.225:8000", "192.168.31.225"),
    Case("wss 前缀保持", "wss://tunnel.example.com", "tunnel.example.com"),
]


def run() -> int:
    print("=" * 70)
    print("WebSocketManager.normalizeWsScheme 修复验证")
    print("=" * 70)

    failures: list[str] = []

    for case in CASES:
        print(f"\n[用例] {case.name}")
        print(f"  backendUrl = {case.backend_url!r}")

        # 旧实现
        old_url = build_ws_url(case.backend_url, buggy_normalize_ws_scheme)
        old_host, old_path = parse_host_path(old_url)
        old_ok = (old_host == case.expected_host and old_path == case.expected_path)
        print(f"  旧实现: wsUrl={old_url!r}")
        print(f"          host={old_host!r} path={old_path!r}  {'OK' if old_ok else 'BAD (403 根因)'}")

        # 新实现
        new_url = build_ws_url(case.backend_url, fixed_normalize_ws_scheme)
        new_host, new_path = parse_host_path(new_url)
        new_ok = (new_host == case.expected_host and new_path == case.expected_path)
        print(f"  新实现: wsUrl={new_url!r}")
        print(f"          host={new_host!r} path={new_path!r}  {'OK' if new_ok else 'BAD'}")

        if not new_ok:
            failures.append(
                f"{case.name}: 期望 host={case.expected_host!r} path={case.expected_path!r}, "
                f"实际 host={new_host!r} path={new_path!r}"
            )

    # 关键回归：旧实现一定在 http:// 场景下产生畸形 URL
    print("\n" + "=" * 70)
    print("关键回归断言：旧实现把 http://host 拼成 wss://http://host")
    print("=" * 70)
    for url in ["http://192.168.31.225:8000", "https://tunnel.example.com"]:
        old = build_ws_url(url, buggy_normalize_ws_scheme)
        malformed = old.startswith("wss://http") or old.startswith("wss://https")
        print(f"  {url!r} -> 旧实现={old!r}  畸形={malformed}")
        if not malformed:
            failures.append(f"旧实现未在 {url!r} 上产生畸形 URL，回归假设不成立")

    print()
    if failures:
        print(f"失败 {len(failures)} 项:")
        for f in failures:
            print(f"  X {f}")
        return 1

    print("全部通过：新实现能正确转换协议头，host/path 解析正确，不再 403。")
    return 0


if __name__ == "__main__":
    sys.exit(run())
