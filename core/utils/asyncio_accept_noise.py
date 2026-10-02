"""Windows Proactor accept 噪音治理与监听自愈。

背景
----
Windows 下 uvicorn 跑在 Proactor 事件循环上（asyncio 在 Windows 的默认策略）。
当客户端在服务器完成 accept 之前就断开（端口探测、健康检查、移动端网络切换、
客户端超时重连等），IOCP 的 AcceptEx 会返回 WinError 64
（ERROR_NETNAME_DELETED，"指定的网络名不再可用"）。asyncio 内部有两条路径会把
它当成异常打进日志：

1. ``proactor_events.BaseProactorEventLoop._start_serving`` 的 accept 回调里
   ``future.result()`` 抛 OSError，于是调用
   ``loop.call_exception_handler({"message": "Accept failed on a socket", ...})``，
   默认处理器打一条 ERROR 加完整堆栈；**并且它紧接着 ``sock.close()`` 关掉监听
   socket**——此后 accept 循环只在已关闭的 socket 上静默失败，服务看起来还活着，
   实际再也接不了新连接。
2. accept 的 future 异常无人取回，``accept_coro`` 任务析构时触发
   ``loop.call_exception_handler({"message": "Task exception was never retrieved", ...})``，
   又是一条 ERROR 加堆栈。

两者都属于"对端断开"的噪音，不代表服务故障。本模块做三件事：

* :func:`install_proactor_accept_patch`：给 Proactor 的 ``_start_serving`` 打补丁，
  瞬态网络错误只记 debug、不关闭监听 socket，监听循环继续 accept；
  设 ``XIAOYOU_DISABLE_ACCEPT_NOISE_PATCH=1`` 可跳过补丁（只留降噪与自愈）；
* :func:`install_accept_noise_guard`：给事件循环装异常处理器，把上述两条噪音压到
  debug 级（其它异常仍走默认处理器，真故障不会被吞）；
* 兜底自愈：万一补丁没生效（例如将来 CPython 改了内部实现），异常处理器在检测到
  监听 socket 已被关闭时，用注入的 ``socket_factory`` 自动重建监听。

补丁必须保持"同一时刻只挂起一个 AcceptEx"这条不变式，细节见
:func:`start_serving_keep_listener` 的 docstring。

非 Windows 平台全部为 no-op。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import sys
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ACCEPT_FAILED_MESSAGE = "Accept failed on a socket"
TASK_EXCEPTION_MESSAGE = "Task exception was never retrieved"

# 判定为"对端断开/套接字已关"的 Windows 错误码，这类 accept 失败属于噪音：
#   64    ERROR_NETNAME_DELETED  指定的网络名不再可用（对端在 accept 前断开）
#   995   ERROR_OPERATION_ABORTED 线程退出或中止请求导致的 I/O 取消
#   10038 WSAENOTSOCK           套接字已关闭（关闭阶段的收尾噪音）
#   10053 WSAECONNABORTED       软件导致连接中止
#   10054 WSAECONNRESET         远程主机强制关闭连接
#   10058 WSAESHUTDOWN          套接字关闭后继续收发
TRANSIENT_WINERRORS = frozenset({64, 995, 10038, 10053, 10054, 10058})

# 连续多少次"连连接都没等来就同步失败"后放弃保留监听（防止任何形式的忙循环）
_MAX_CONSECUTIVE_SYNC_FAILURES = 8

# 紧急开关：设成 1/true/yes/on 时不打补丁（只保留日志降噪与监听自愈）
ENV_DISABLE_PATCH = "XIAOYOU_DISABLE_ACCEPT_NOISE_PATCH"

_PATCH_FLAG = "_xiaoyou_accept_noise_patched"
_ORIGINAL_ATTR = "_xiaoyou_original_start_serving"

# 补丁依赖的 CPython 内部签名；缺任意参数就放弃打补丁（宁可保留原生行为，
# 也不要拿旧实现去覆盖新版本的重构）。
_REQUIRED_PARAMS = (
    "protocol_factory",
    "sock",
    "sslcontext",
    "server",
    "backlog",
    "ssl_handshake_timeout",
)

# 保持 guard 强引用，避免仅被 loop 异常处理器弱引用时被回收
_ACTIVE_GUARDS: "dict[int, AcceptNoiseGuard]" = {}


def _find_transient_winerror(exception: Optional[BaseException]) -> Optional[int]:
    """沿异常链查找瞬态网络错误码；找不到返回 None。

    与 ``core/utils/websocket_logging._find_windows_error`` 同样需要一个 seen
    集合抵御自引用/成环的异常链。
    """
    seen: set[int] = set()
    current: Optional[BaseException] = exception
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        winerror = getattr(current, "winerror", None)
        if winerror in TRANSIENT_WINERRORS:
            return winerror
        current = current.__cause__ or current.__context__
    return None


def is_transient_network_error(exception: Optional[BaseException]) -> bool:
    """异常（或其 cause/context 链）是否是"对端断开"类瞬态网络错误。"""
    return _find_transient_winerror(exception) is not None


def _transport_socket(sock):
    """包装成 TransportSocket 供异常上下文展示，导入失败时退化为原 socket。"""
    try:
        from asyncio.trsock import TransportSocket

        return TransportSocket(sock)
    except Exception:
        return sock


def _listeners_all_closed(server: Any) -> bool:
    """uvicorn Server 上的监听 socket 是否已全部关闭（= 服务已接不了新连接）。"""
    sockets = []
    for item in getattr(server, "servers", None) or []:
        sockets.extend(getattr(item, "sockets", None) or [])
    if not sockets:
        return False
    return all(sock.fileno() == -1 for sock in sockets)


def start_serving_keep_listener(
    event_loop,
    protocol_factory,
    sock,
    sslcontext=None,
    server=None,
    backlog=100,
    ssl_handshake_timeout=None,
    ssl_shutdown_timeout=None,
):
    """复刻 ``BaseProactorEventLoop._start_serving``，但瞬态错误不关闭监听 socket。

    与原实现的两点差别（其余逐行一致）：

    1. ``future.result()`` 抛瞬态网络错误（对端在 accept 完成前断开，WinError
       64/995/10038/10053/10054/10058）时，记 debug 并重新挂起 accept，而不是让
       accept 循环就此终止，也不 ``sock.close()``；
    2. 监听 socket 失效（``fileno() == -1``）时结束循环，不像原实现那样在已关闭的
       socket 上无止境地空转。

    **不变式（务必保持）**：任何时刻只挂起一个 AcceptEx——原实现里 ``loop`` 由
    ``f.add_done_callback(loop)`` 驱动，``call_soon(loop)`` 只在启动时调一次。
    一旦改成"每轮都 ``call_soon(loop)``"，就会不等上一个 AcceptEx 完成而不断挂起
    新的，每个挂起都带一个 accept socket + future + task，内存与句柄会一路涨到耗尽
    （本项目曾因此踩坑）。
    """
    sync_failures = 0

    def accept_loop(future=None):
        nonlocal sync_failures
        try:
            if future is not None:
                conn, addr = future.result()
                if getattr(event_loop, "_debug", False):
                    logger.debug("%r got a new connection from %r: %r", server, addr, conn)
                protocol = protocol_factory()
                if sslcontext is not None:
                    kwargs = {
                        "server_side": True,
                        "extra": {"peername": addr},
                        "server": server,
                        "ssl_handshake_timeout": ssl_handshake_timeout,
                    }
                    # ssl_shutdown_timeout 是 3.11+ 才有的参数，老版本不传
                    if ssl_shutdown_timeout is not None:
                        kwargs["ssl_shutdown_timeout"] = ssl_shutdown_timeout
                    event_loop._make_ssl_transport(conn, protocol, sslcontext, **kwargs)
                else:
                    event_loop._make_socket_transport(
                        conn, protocol, extra={"peername": addr}, server=server
                    )
            if event_loop.is_closed():
                return
            next_future = event_loop._proactor.accept(sock)
        except OSError as exc:
            if sock.fileno() == -1:
                # 监听 socket 已被关闭（server.close()/shutdown 等）：结束循环，
                # 不在失效 socket 上空转。
                if getattr(event_loop, "_debug", False):
                    logger.debug("监听 socket 已关闭，accept 循环结束", exc_info=True)
                return
            if is_transient_network_error(exc):
                if future is None:
                    # 连连接都还没等来就同步失败：保守限次，杜绝任何形式的忙循环
                    sync_failures += 1
                    if sync_failures > _MAX_CONSECUTIVE_SYNC_FAILURES:
                        event_loop.call_exception_handler(
                            {
                                "message": ACCEPT_FAILED_MESSAGE,
                                "exception": exc,
                                "socket": _transport_socket(sock),
                            }
                        )
                        sock.close()
                        return
                else:
                    sync_failures = 0
                logger.debug("accept 瞬态失败（对端在握手前断开），保留监听 socket：%r", exc)
                event_loop.call_soon(accept_loop)
                return
            event_loop.call_exception_handler(
                {
                    "message": ACCEPT_FAILED_MESSAGE,
                    "exception": exc,
                    "socket": _transport_socket(sock),
                }
            )
            sock.close()
            return
        except asyncio.CancelledError:
            sock.close()
            return

        sync_failures = 0
        # 与原实现一致：只挂一个 AcceptEx，由 future 完成回调驱动下一轮，
        # 这里不能再 call_soon，否则会把挂起数翻倍并持续泄漏。
        event_loop._accept_futures[sock.fileno()] = next_future
        next_future.add_done_callback(accept_loop)

    event_loop.call_soon(accept_loop)


def _patched_start_serving(self, *args, **kwargs):
    """安装到 Proactor loop 上的替代实现（签名用 *args 透传，规避版本差异）。"""
    return start_serving_keep_listener(self, *args, **kwargs)


def _start_serving_signature_supported(func: Any) -> bool:
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return all(name in params for name in _REQUIRED_PARAMS)


def _patch_disabled_by_env() -> bool:
    """是否被紧急开关禁用补丁。"""
    return os.environ.get(ENV_DISABLE_PATCH, "").strip().lower() in {"1", "true", "yes", "on"}


def install_proactor_accept_patch() -> bool:
    """给 Windows Proactor 事件循环打 accept 补丁。

    Returns:
        本次是否完成安装；重复安装、平台/版本不匹配或被环境变量禁用时返回 False。
    """
    if sys.platform != "win32":
        return False
    if _patch_disabled_by_env():
        logger.warning(
            "%s 已设置，跳过 accept 补丁（仅保留日志降噪与监听自愈）", ENV_DISABLE_PATCH
        )
        return False
    try:
        from asyncio.proactor_events import BaseProactorEventLoop
    except Exception:
        return False
    if getattr(BaseProactorEventLoop, _PATCH_FLAG, False):
        return False
    if not _start_serving_signature_supported(BaseProactorEventLoop._start_serving):
        logger.warning(
            "asyncio 内部实现与预期不符，跳过 accept 补丁（改由日志抑制与监听自愈兜底）"
        )
        return False
    setattr(BaseProactorEventLoop, _ORIGINAL_ATTR, BaseProactorEventLoop._start_serving)
    BaseProactorEventLoop._start_serving = _patched_start_serving
    setattr(BaseProactorEventLoop, _PATCH_FLAG, True)
    return True


def uninstall_proactor_accept_patch() -> bool:
    """还原 ``_start_serving``（主要给测试与排障用）。"""
    try:
        from asyncio.proactor_events import BaseProactorEventLoop
    except Exception:
        return False
    original = getattr(BaseProactorEventLoop, _ORIGINAL_ATTR, None)
    if original is None:
        return False
    BaseProactorEventLoop._start_serving = original
    setattr(BaseProactorEventLoop, _PATCH_FLAG, False)
    return True


class AcceptNoiseGuard:
    """事件循环异常处理器：抑制 accept 噪音，必要时自愈监听。

    Args:
        server: uvicorn ``Server`` 实例，用于自愈时定位监听与复刻协议工厂。
        socket_factory: 无参可调用，返回一个已 bind+listen 的 socket；用于重建监听。
        previous_handler: 原异常处理器，非噪音异常优先交回它处理。
    """

    def __init__(
        self,
        server: Any = None,
        socket_factory: Optional[Callable[[], Any]] = None,
        previous_handler: Optional[Callable[[Any, dict], None]] = None,
    ) -> None:
        self.server = server
        self.socket_factory = socket_factory
        self.previous_handler = previous_handler
        self._recovery_scheduled = False

    def handle_exception(self, loop, context: dict) -> None:
        message = str(context.get("message") or "")
        exception = context.get("exception")
        if message == ACCEPT_FAILED_MESSAGE and is_transient_network_error(exception):
            logger.warning(
                "检测到 Windows accept 瞬态失败（对端在握手前断开），已安排监听自愈：%r",
                exception,
            )
            self.schedule_listen_recovery(loop)
            return
        if message == TASK_EXCEPTION_MESSAGE and is_transient_network_error(exception):
            logger.debug("已抑制 asyncio 瞬态网络异常日志：%s (%r)", message, exception)
            return
        self._delegate(loop, context)

    def _delegate(self, loop, context: dict) -> None:
        if self.previous_handler is not None:
            self.previous_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    def schedule_listen_recovery(self, loop) -> None:
        """安排一次"监听是否已被关闭"的检查（补丁失效时的兜底）。"""
        if self.server is None or self.socket_factory is None or self._recovery_scheduled:
            return
        self._recovery_scheduled = True
        try:
            loop.call_soon(self._recover_listening, loop)
        except Exception as exc:  # loop 已关闭等情况，不影响主流程
            logger.debug("监听自愈调度失败：%r", exc)
            self._recovery_scheduled = False

    def _recover_listening(self, loop) -> None:
        try:
            if _listeners_all_closed(self.server):
                loop.create_task(self._rebuild_listeners(loop))
        except Exception as exc:
            logger.error("监听自愈调度失败，请重启服务：%r", exc)
        finally:
            self._recovery_scheduled = False

    async def _rebuild_listeners(self, loop) -> None:
        try:
            config = self.server.config
            protocol_class = config.http_protocol_class
            app_state = getattr(getattr(self.server, "lifespan", None), "state", None)
            listen_socket = self.socket_factory()

            def create_protocol(_loop=None):
                return protocol_class(
                    config=config,
                    server_state=self.server.server_state,
                    app_state=app_state,
                    _loop=_loop,
                )

            new_server = await loop.create_server(
                create_protocol,
                sock=listen_socket,
                ssl=getattr(config, "ssl", None),
                backlog=int(getattr(config, "backlog", 2048) or 2048),
            )
        except Exception as exc:
            logger.error("监听 socket 已被瞬态 accept 错误关闭，自动重建失败，请重启服务：%r", exc)
            return

        for old_server in list(getattr(self.server, "servers", []) or []):
            try:
                old_server.close()
            except Exception:
                pass
        self.server.servers = [new_server]
        logger.warning("监听 socket 曾被瞬态 accept 错误关闭，已自动重建监听")


def install_accept_noise_guard(
    loop,
    *,
    server: Any = None,
    socket_factory: Optional[Callable[[], Any]] = None,
) -> Optional[AcceptNoiseGuard]:
    """在指定事件循环上安装噪音治理（非 Windows 返回 None）。"""
    if sys.platform != "win32":
        return None
    guard = AcceptNoiseGuard(
        server=server,
        socket_factory=socket_factory,
        previous_handler=loop.get_exception_handler(),
    )
    _ACTIVE_GUARDS[id(loop)] = guard
    loop.set_exception_handler(guard.handle_exception)
    return guard


def run_server_with_accept_noise_guard(
    server,
    sockets=None,
    socket_factory: Optional[Callable[[], Any]] = None,
):
    """安装 Windows accept 噪音治理后运行 uvicorn ``Server``。

    与 ``Server.run()`` 的差别：自建事件循环，以便在 loop 创建后、开始服务前装上
    异常处理器与 accept 补丁（``Server.run()`` 内部直接 ``asyncio.run``，没有
    插入点）。Windows 上 uvloop 不可用，因此两者的循环类型一致；非 Windows 平台
    行为完全不变，直接透传给 ``Server.run()``。
    """
    if sys.platform != "win32":
        return server.run(sockets=sockets)

    install_proactor_accept_patch()

    async def _serve():
        install_accept_noise_guard(
            asyncio.get_running_loop(),
            server=server,
            socket_factory=socket_factory,
        )
        await server.serve(sockets=sockets)

    return asyncio.run(_serve())
