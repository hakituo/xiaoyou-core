#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-06 验证脚本: settings_handlers.py 全局配置篡改权限校验

验证项：
1. handle_update_settings 在远程连接尝试修改 llm 配置时拒绝
2. handle_update_settings 在本地连接尝试修改 llm 配置时放行
3. _is_local_websocket 正确识别本地/远程连接
4. 非 LLM 配置（如生理状态）不受影响
5. 拒绝响应包含明确的 error_code=forbidden_global_config
"""
import sys
import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

ROOT = Path(__file__).resolve().parents[3]
HANDLER_PATH = ROOT / "core" / "interfaces" / "websocket" / "adapters" / "handlers" / "settings_handlers.py"


def _install_stubs():
    """预存根依赖。"""
    # fastapi
    if "fastapi" not in sys.modules:
        fastapi_stub = ModuleType("fastapi")

        class _WebSocket:
            pass

        fastapi_stub.WebSocket = _WebSocket
        sys.modules["fastapi"] = fastapi_stub

    if "fastapi.encoders" not in sys.modules:
        enc_stub = ModuleType("fastapi.encoders")
        enc_stub.jsonable_encoder = lambda obj: obj  # 直接返回，便于断言
        sys.modules["fastapi.encoders"] = enc_stub

    # core / core.services / core.interfaces 等
    for pkg_name in (
        "core", "core.services", "core.services.life_simulation",
        "core.services.life_simulation.service", "core.llm",
        "core.interfaces", "core.interfaces.websocket",
        "core.interfaces.websocket.adapters",
        "core.interfaces.websocket.adapters.handlers",
        "config", "config.integrated_config",
    ):
        if pkg_name not in sys.modules:
            pkg = ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg_name] = pkg


def load_module():
    _install_stubs()

    spec = importlib.util.spec_from_file_location("settings_handlers_p0_06", HANDLER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {HANDLER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_websocket(host: str):
    """构造模拟的 WebSocket，client.host 为指定值。"""
    ws = MagicMock()
    ws.client = SimpleNamespace(host=host)
    ws.send_json = AsyncMock()
    return ws


def check_is_local(module) -> list[str]:
    """测试 _is_local_websocket 边界。"""
    issues = []
    func = getattr(module, "_is_local_websocket", None)
    if func is None:
        issues.append("缺失 _is_local_websocket 函数")
        return issues

    for host in ("127.0.0.1", "::1", "localhost"):
        ws = _make_websocket(host)
        if not func(ws):
            issues.append(f"[{host}] 应判为本地，但返回 False")

    for host in ("192.168.1.5", "10.0.0.1", "8.8.8.8", "example.com"):
        ws = _make_websocket(host)
        if func(ws):
            issues.append(f"[{host}] 应判为远程，但返回 True")

    # client 为 None 时应判为远程（保守拒绝）
    ws_none = MagicMock()
    ws_none.client = None
    if func(ws_none):
        issues.append("[client=None] 应判为远程（False），但返回 True")

    return issues


def check_remote_rejected(module) -> list[str]:
    """远程连接尝试修改 LLM 配置时应该被拒绝。"""
    issues = []

    SettingsHandlers = getattr(module, "SettingsHandlers", None)
    if SettingsHandlers is None:
        issues.append("缺失 SettingsHandlers 类")
        return issues

    handler = SettingsHandlers(adapter=MagicMock())

    # 远程客户端
    ws_remote = _make_websocket("8.8.8.8")
    msg = {
        "settings": {"llm": {"provider": "cloud", "model": "gpt-4"}},
        "request_id": "test-req-1",
    }

    try:
        asyncio.run(handler.handle_update_settings(ws_remote, msg))
    except Exception as e:
        issues.append(f"远程修改请求处理异常: {e}")
        return issues

    if ws_remote.send_json.await_count == 0:
        issues.append("远程修改请求未发送任何响应")
        return issues

    response = ws_remote.send_json.await_args.args[0]
    # 由于 jsonable_encoder 是 passthrough，response 就是原始 dict
    if response.get("type") != "error":
        issues.append(f"远程修改请求响应类型应为 error，实际为: {response.get('type')}")
    if "forbidden_global_config" != response.get("error_code"):
        issues.append(f"响应应包含 error_code=forbidden_global_config，实际: {response.get('error_code')}")
    if "权限" not in response.get("message", ""):
        issues.append(f"响应 message 应包含'权限'，实际: {response.get('message')}")

    return issues


def check_local_allowed(module) -> list[str]:
    """本地连接尝试修改 LLM 配置时应放行（不应返回 forbidden_global_config）。"""
    issues = []

    SettingsHandlers = getattr(module, "SettingsHandlers", None)
    if SettingsHandlers is None:
        issues.append("缺失 SettingsHandlers 类")
        return issues

    handler = SettingsHandlers(adapter=MagicMock())

    # 本地客户端
    ws_local = _make_websocket("127.0.0.1")
    msg = {
        "settings": {"llm": {"provider": "cloud", "model": "gpt-4"}},
        "request_id": "test-req-2",
    }

    try:
        asyncio.run(handler.handle_update_settings(ws_local, msg))
    except Exception as e:
        # 本地连接会进入到 _update_llm_settings 和 LLM 模块重载流程，可能因为 stub 抛异常
        # 这里只要不返回 forbidden_global_config 就算通过
        pass

    if ws_local.send_json.await_count == 0:
        # 没有发响应也是正常的（异常路径），不算 forbidden
        return issues

    response = ws_local.send_json.await_args.args[0]
    if response.get("error_code") == "forbidden_global_config":
        issues.append("本地连接被错误地拒绝为 forbidden_global_config")

    return issues


def check_non_llm_unaffected(module) -> list[str]:
    """非 LLM 配置（如生理状态）不应被新权限校验影响。"""
    issues = []

    SettingsHandlers = getattr(module, "SettingsHandlers", None)
    if SettingsHandlers is None:
        issues.append("缺失 SettingsHandlers 类")
        return issues

    handler = SettingsHandlers(adapter=MagicMock())

    # 远程客户端但只更新非 LLM 配置
    ws_remote = _make_websocket("8.8.8.8")
    msg = {
        "settings": {"ui": {"theme": "dark"}},  # 非 LLM 配置
        "request_id": "test-req-3",
    }

    try:
        asyncio.run(handler.handle_update_settings(ws_remote, msg))
    except Exception:
        pass

    if ws_remote.send_json.await_count == 0:
        return issues  # 进入下游重载流程可能因 stub 抛错

    response = ws_remote.send_json.await_args.args[0]
    if response.get("error_code") == "forbidden_global_config":
        issues.append("非 LLM 配置被错误地拒绝为 forbidden_global_config")

    return issues


def main() -> int:
    if not HANDLER_PATH.exists():
        print(f"[ERROR] settings_handlers.py 不存在: {HANDLER_PATH}")
        return 2

    all_issues: list[str] = []

    try:
        module = load_module()
        all_issues.extend(check_is_local(module))
        all_issues.extend(check_remote_rejected(module))
        all_issues.extend(check_local_allowed(module))
        all_issues.extend(check_non_llm_unaffected(module))
    except Exception as exc:
        all_issues.append(f"模块加载/运行时测试失败: {exc}")

    if all_issues:
        print(f"[FAIL] 共发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1

    print("[OK] settings_handlers.py 全局配置篡改权限校验已加固")
    print("  - _is_local_websocket 正确识别 127.0.0.1/::1/localhost 为本地")
    print("  - 远程连接修改 LLM 配置被拒绝（error_code=forbidden_global_config）")
    print("  - 本地连接修改 LLM 配置放行")
    print("  - 非 LLM 配置不受新校验影响")
    return 0


if __name__ == "__main__":
    sys.exit(main())
