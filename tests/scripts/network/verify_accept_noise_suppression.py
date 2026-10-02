#!/usr/bin/env python3
"""验证 Windows Proactor accept 噪音治理（core/utils/asyncio_accept_noise.py）。

运行：
    venv_core\\Scripts\\python.exe tests/scripts/network/verify_accept_noise_suppression.py

覆盖：
1. 补丁可安装/可还原且幂等（Windows）；
2. 打了补丁后真实事件循环仍能正常 accept（服务不接受连接才是灾难）；
3. 循环异常处理器把 accept 噪音压成非 ERROR 日志，同时真故障仍照常上报；
4. 补丁失效（监听 socket 被 asyncio 关掉）时，兜底自愈能重建监听并接受新连接；
5. accept 失败风暴下句柄数不得持续增长（钉死"同一时刻只挂一个 AcceptEx"的不变式，
   违反它会不断向内核挂起新的 accept 并泄漏 socket/future/task）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import struct
import sys
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import asyncio_accept_noise as mod  # noqa: E402

try:  # psutil 是运行期依赖，缺失时只跳过句柄检查
    import psutil
except Exception:  # pragma: no cover - 环境缺失依赖
    psutil = None


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _NullProtocol(asyncio.Protocol):
    """最小 HTTP 协议替身：只需接受 uvicorn 协议构造签名。"""

    def __init__(self, config=None, server_state=None, app_state=None, _loop=None):
        self.config = config


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def make_listen_socket(host: str = "127.0.0.1") -> socket.socket:
    """自愈重建监听用的 socket 工厂（端口 0：由系统分配空闲端口）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(64)
    return sock


def check_transient_detection() -> None:
    """纯逻辑检查：哪些错误码算"对端断开"噪音。"""
    error = OSError(22, "指定的网络名不再可用。", None, 64)
    require(mod.is_transient_network_error(error) is True, "WinError 64 应判定为瞬态网络错误")
    require(mod.is_transient_network_error(None) is False, "None 不应判定为瞬态错误")
    require(
        mod.is_transient_network_error(ValueError("boom")) is False,
        "普通异常不应判定为瞬态网络错误",
    )


def check_patch_round_trip() -> bool:
    """Windows 上补丁应可安装、幂等、可还原。"""
    if sys.platform != "win32":
        print("[skip] 非 Windows 平台：Proactor 补丁不适用")
        return False

    from asyncio.proactor_events import BaseProactorEventLoop

    original = BaseProactorEventLoop._start_serving
    require(mod.install_proactor_accept_patch() is True, "补丁安装失败")
    try:
        require(
            BaseProactorEventLoop._start_serving is mod._patched_start_serving,
            "补丁未真正替换 _start_serving",
        )
        require(mod.install_proactor_accept_patch() is False, "补丁应幂等（重复安装不再叠加）")
    finally:
        require(mod.uninstall_proactor_accept_patch() is True, "补丁还原失败")
        require(
            BaseProactorEventLoop._start_serving is original,
            "补丁还原后 _start_serving 应回到原实现",
        )
    print("[ok] 补丁安装 / 幂等 / 还原")
    return True


async def _accept_smoke() -> None:
    """真实事件循环上跑一次完整 accept + 收发，确认补丁没弄坏服务。"""
    mod.install_accept_noise_guard(asyncio.get_running_loop())  # 顺带验证 guard 可安装

    class EchoProtocol(asyncio.Protocol):
        def connection_made(self, transport):
            self.transport = transport

        def data_received(self, data):
            self.transport.write(b"pong:" + data)

    loop = asyncio.get_running_loop()
    server = await loop.create_server(EchoProtocol, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b"ping")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(64), timeout=5)
            require(data == b"pong:ping", f"补丁后 accept/收发异常：{data!r}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
    finally:
        server.close()
        await server.wait_closed()


async def _failure_storm_probe() -> None:
    """高频"连接后立刻 RST"风暴下，句柄数不得持续增长。"""
    if psutil is None:
        print("[skip] psutil 不可用：跳过失败风暴句柄检查")
        return

    proc = psutil.Process(os.getpid())
    loop = asyncio.get_running_loop()
    mod.install_accept_noise_guard(loop)  # 让风暴期间的瞬态失败只记 debug

    class SinkProtocol(asyncio.Protocol):
        def connection_made(self, transport):
            transport.close()

    server = await loop.create_server(SinkProtocol, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    stop = threading.Event()

    def storm():
        while not stop.is_set():
            client = socket.socket()
            # SO_LINGER=0：close 直接发 RST，制造"对端在 accept 完成前断开"
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            try:
                client.connect(("127.0.0.1", port))
            except OSError:
                pass
            client.close()
            time.sleep(0.002)

    worker = threading.Thread(target=storm, daemon=True)
    worker.start()
    try:
        # 先让风暴跑热，再取基线，避免把启动噪声算成增长
        for _ in range(4):
            time.sleep(0.3)
            await asyncio.sleep(0.05)
        baseline = proc.num_handles()
        for _ in range(8):
            time.sleep(0.3)  # 阻塞 loop：让内核先完成握手再 RST
            await asyncio.sleep(0.05)
        grown = proc.num_handles() - baseline
        listener_alive = all(sock.fileno() != -1 for sock in server.sockets)
    finally:
        stop.set()
        worker.join(timeout=2)
        server.close()
        await server.wait_closed()

    require(listener_alive, "失败风暴后监听 socket 被关闭，服务已无法接受新连接")
    require(grown <= 20, f"accept 失败风暴下句柄持续增长（+{grown}），疑似 accept 泄漏")


def check_accept_still_works() -> None:
    if sys.platform != "win32":
        print("[skip] 非 Windows 平台：跳过 Proactor accept 冒烟")
        return

    mod.install_proactor_accept_patch()
    try:
        asyncio.run(_accept_smoke())
        print("[ok] 补丁后真实 accept / 收发正常")
        asyncio.run(_failure_storm_probe())
    finally:
        mod.uninstall_proactor_accept_patch()
    print("[ok] accept 失败风暴下句柄稳定（无泄漏）")


def check_guard_logging() -> None:
    """accept 噪音不上报 ERROR，真故障仍走默认处理器。"""
    if sys.platform != "win32":
        print("[skip] 非 Windows 平台：guard 只在 Windows 安装")
        return

    root = logging.getLogger()
    capture = _CaptureHandler()
    previous_level = root.level
    root.addHandler(capture)
    root.setLevel(logging.ERROR)

    loop = asyncio.new_event_loop()
    try:
        guard = mod.install_accept_noise_guard(loop)
        require(guard is not None, "Windows 上 guard 应安装成功")

        noise = OSError(22, "指定的网络名不再可用。", None, 64)
        loop.call_exception_handler({"message": mod.TASK_EXCEPTION_MESSAGE, "exception": noise})
        require(capture.records == [], "accept 噪音不应产生 ERROR 日志")

        loop.call_exception_handler({"message": "真故障", "exception": RuntimeError("boom")})
        require(capture.records != [], "真实异常必须仍然上报（不能被噪声过滤吞掉）")
        require(
            any(
                record.exc_info and isinstance(record.exc_info[1], RuntimeError)
                for record in capture.records
            ),
            "真实异常必须带异常详情输出",
        )
    finally:
        loop.close()
        root.removeHandler(capture)
        root.setLevel(previous_level)
    print("[ok] 噪音不产生 ERROR 日志，真实异常仍上报")


async def _self_heal_smoke() -> None:
    """监听 socket 被关掉后，自愈应重建监听并能接受新连接。"""
    loop = asyncio.get_running_loop()
    dead_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dead_socket.close()  # fileno() == -1，模拟被 asyncio 关掉的监听

    old_asyncio_server = types.SimpleNamespace(sockets=[dead_socket])
    fake_config = types.SimpleNamespace(
        http_protocol_class=_NullProtocol,
        ssl=None,
        backlog=100,
    )
    fake_server = types.SimpleNamespace(
        config=fake_config,
        server_state=object(),
        lifespan=types.SimpleNamespace(state={}),
        servers=[old_asyncio_server],
    )

    guard = mod.AcceptNoiseGuard(server=fake_server, socket_factory=make_listen_socket)
    guard.schedule_listen_recovery(loop)

    for _ in range(500):
        if fake_server.servers[0] is not old_asyncio_server:
            break
        await asyncio.sleep(0.01)

    new_server = fake_server.servers[0]
    require(new_server is not old_asyncio_server, "监听被关闭后未自动重建")
    require(new_server.sockets, "重建后的监听缺少 socket")

    port = new_server.sockets[0].getsockname()[1]
    try:
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        require(writer is not None, "重建后的监听无法接受新连接")
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
    finally:
        new_server.close()
        await new_server.wait_closed()


def main() -> None:
    check_transient_detection()
    print("[ok] 瞬态网络错误判定")

    if check_patch_round_trip():
        check_accept_still_works()

    check_guard_logging()
    asyncio.run(_self_heal_smoke())
    print("[ok] 监听自愈：重建后可接受新连接")

    print("验证通过：accept 噪音已降噪，监听不会被瞬态错误永久关闭")


if __name__ == "__main__":
    main()
