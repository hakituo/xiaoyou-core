r"""验证 auto_commit_push 的联网就绪检测不会把"TCP 通了"误判成"网络已就绪"。

背景（2026-09-21 实测）：代理节点挂掉时，TCP 连 github.com:443 仍然能建立，
但 TLS 握手会以 `unexpected eof while reading` 失败，git / curl 都连不上 GitHub。
旧实现里 fallback 只做 `socket.create_connection(...)` 就 `return True`，
于是脚本判定"网络已就绪" → 继续走到 push → push 失败却没被识别，
最终打印「[完成] 自动提交成功」，**实际一个提交都没推上去**。

保护口径：
1. `git ls-remote` 走通 → 就绪（不碰 TLS 探测，保持"代理端口非 443 也能用"的兼容性）；
2. `git ls-remote` 失败 + TLS 握手成功 → 就绪（无代理环境）；
3. `git ls-remote` 失败 + TCP 通但 TLS 握手失败 → **不就绪**（本次修复的核心）；
4. `tls_probe()` 本身：握手失败必须返回 False。

运行：
    D:\projects\xiaoyou\venv_core\Scripts\python.exe -m tests.scripts.git.verify_network_ready_tls
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_FAILED: list[str] = []

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.git.auto_commit_push import (  # noqa: E402
    check_network_ready,
    tls_probe,
)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    _FAILED.append(msg)


def _mock_run_cmd(code: int):
    """构造假的 run_cmd：统一返回指定退出码（0=git ls-remote 走通）。"""

    def _run(cmd, cwd=None, timeout=30, env=None):
        return code, "", "" if code == 0 else "fatal: unable to access ..."

    return _run


def _mock_tls_probe(result: bool):
    """构造假的 tls_probe，并记录是否被调用。"""
    calls: list[bool] = []

    def _probe(host=None, port=None, timeout=None):
        calls.append(result)
        return result

    _probe.calls = calls  # type: ignore[attr-defined]
    return _probe


def test_git_path_short_circuits() -> None:
    print("\n=== 测试 1: git ls-remote 走通 -> 就绪，且不再做 TLS 探测 ===")
    probe = _mock_tls_probe(False)
    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=_mock_run_cmd(0)), patch(
        "scripts.git.auto_commit_push.tls_probe", side_effect=probe
    ):
        ready = check_network_ready(timeout=5)
    if ready and not probe.calls:  # type: ignore[attr-defined]
        _ok("git 走通即就绪，未多余探测")
    elif not ready:
        _fail("git ls-remote 走通却被判定为不就绪")
    else:
        _fail("git 走通后又多做了一次 TLS 探测（无必要）")


def test_tls_fallback_when_git_fails() -> None:
    print("\n=== 测试 2: git 失败但 TLS 握手成功 -> 就绪（无代理环境） ===")
    probe = _mock_tls_probe(True)
    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=_mock_run_cmd(1)), patch(
        "scripts.git.auto_commit_push.tls_probe", side_effect=probe
    ):
        ready = check_network_ready(timeout=5)
    if ready and probe.calls:  # type: ignore[attr-defined]
        _ok("退化为 TLS 探测并判定就绪")
    else:
        _fail("git 失败 + TLS 通，却未判定为就绪")


def test_tcp_only_must_not_be_ready() -> None:
    print("\n=== 测试 3（核心）: TCP 通但 TLS 握手失败 -> 必须判定为不就绪 ===")
    probe = _mock_tls_probe(False)
    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=_mock_run_cmd(1)), patch(
        "scripts.git.auto_commit_push.tls_probe", side_effect=probe
    ):
        ready = check_network_ready(timeout=0.1)
    if not ready:
        _ok("未把「TCP 通」当成「网络已就绪」，脚本会正确报网络不可用并终止")
    else:
        _fail("TCP 通、TLS 挂，仍被判定为就绪 —— 会导致谎报提交成功")


def test_tls_probe_returns_false_on_handshake_failure() -> None:
    print("\n=== 测试 4: tls_probe 在握手失败时返回 False ===")
    # 指向一个一定不会有合法 TLS 响应的本地端口，钉住"失败即 False"。
    # 不做网络断言，只验证异常被吞掉并返回 False（不抛给调用方）。
    if tls_probe(host="127.0.0.1", port=1, timeout=0.5) is False:
        _ok("握手/连接失败 -> False，不抛异常")
    else:
        _fail("tls_probe 在连不上时未返回 False")


def test_real_github_probe_is_informational() -> None:
    print("\n=== 测试 5（仅参考，不断言）: 当前环境对 github.com 的 TLS 探测 ===")
    result = tls_probe(timeout=5)
    print(f"  [INFO] tls_probe(github.com:443) = {result}（受本机代理节点影响，不作为断言）")


def main() -> int:
    print("=" * 64)
    print("auto_commit_push 联网就绪检测验证（TCP 通 ≠ 网络可用）")
    print("=" * 64)
    test_git_path_short_circuits()
    test_tls_fallback_when_git_fails()
    test_tcp_only_must_not_be_ready()
    test_tls_probe_returns_false_on_handshake_failure()
    test_real_github_probe_is_informational()
    print("=" * 64)
    if _FAILED:
        print(f"失败 {len(_FAILED)} 项：" + "、".join(_FAILED))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
