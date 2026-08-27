"""QQ 适配器会话连接管理模块。

负责 WebSocket 连接循环、重连退避、连接问题诊断与通知。
从 qq_adapter_session.py 拆分而来，采用 session 实例注入策略。
"""
import asyncio
import json
import socket
import time

from clients.bots.qq.settings import logger
from clients.bots.qq.utils import _ws_connect


class SessionConnectionManager:
    """会话连接管理器，负责 WS 连接循环与重连退避。"""

    def __init__(self, session):
        # 持有外层 XiaoyouSession 实例
        self.session = session

    async def run_loop(self):
        """主连接循环：连接 WS、收发消息、异常重连。"""
        session = self.session
        retry_count = 0
        try:
            while session.running:
                try:
                    ws_url = f"{session._cfg.xiaoyou_ws_url}?client_id={session._client_id}&user_id={session.session_id}&platform=qq"
                    headers = None
                    if session._cfg.xiaoyou_access_token:
                        headers = {"Authorization": f"Bearer {session._cfg.xiaoyou_access_token}"}

                    t_conn_start = time.time()
                    async with (await _ws_connect(ws_url, headers=headers)) as ws:
                        t_conn = time.time() - t_conn_start
                        session.ws = ws
                        if session._connection_state != "connected":
                            session._connection_state = "connected"
                            logger.info(f"[{session.session_id}] Connected to Xiaoyou Core (took {t_conn:.3f}s)")

                        try:
                            sock = ws.transport.get_extra_info("socket") if getattr(ws, "transport", None) else None
                            if sock is not None:
                                import socket as _socket

                                sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
                        except Exception:
                            pass
                        retry_count = 0
                        session._last_connected_at = time.time()
                        session._connection_failure_since = 0.0

                        # 连接成功，清除连接失败通知标志位
                        if session.session_id in session.adapter._conn_issue_notified:
                            del session.adapter._conn_issue_notified[session.session_id]

                        receive_task = asyncio.create_task(session._receive_from_xiaoyou())
                        queue_task = None

                        try:
                            while session.running:
                                queue_task = asyncio.create_task(session.queue.get())
                                done, pending = await asyncio.wait(
                                    {queue_task, receive_task},
                                    return_when=asyncio.FIRST_COMPLETED,
                                )

                                if receive_task in done:
                                    for pending_task in pending:
                                        pending_task.cancel()
                                    if queue_task is not None:
                                        try:
                                            await queue_task
                                        except asyncio.CancelledError:
                                            pass
                                        finally:
                                            queue_task = None

                                    if not session.running:
                                        break

                                    recv_exc = None
                                    if not receive_task.cancelled():
                                        recv_exc = receive_task.exception()
                                    if recv_exc is None:
                                        recv_exc = ConnectionError("接收循环已结束，准备重连")
                                    raise recv_exc

                                msg = queue_task.result()
                                queue_task = None
                                real_send_ts = time.time() * 1000
                                orig_ts = msg.get("_send_ts", 0)
                                wait_time = real_send_ts - orig_ts if orig_ts > 0 else 0

                                logger.info(f"[{session.session_id}] [{real_send_ts:.0f}ms] Sending msg to WS (waited {wait_time:.0f}ms in queue)")
                                t_send_start = time.time()
                                await ws.send(json.dumps(msg))
                                send_op_ms = (time.time() - t_send_start) * 1000
                                send_done_ts = time.time() * 1000
                                logger.info(
                                    f"[{session.session_id}] [{send_done_ts:.0f}ms] WS send finished (send_op {send_op_ms:.1f}ms)"
                                )
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            # 连接断开或发送失败：清理 ws 引用，重新抛出以触发外层重连逻辑
                            logger.error(f"[{session.session_id}] Connection loop error: {e}")
                            session.ws = None
                            raise
                        finally:
                            if queue_task is not None:
                                queue_task.cancel()
                                try:
                                    await queue_task
                                except BaseException:
                                    pass
                            receive_task.cancel()
                            try:
                                await receive_task
                            except BaseException:
                                pass

                except Exception as e:
                    err_msg = str(e or "")
                    if not getattr(session, "_connection_failure_since", 0.0):
                        session._connection_failure_since = time.time()
                    is_transient = any(
                        sig in err_msg
                        for sig in (
                            "keepalive ping timeout",
                            "no close frame received",
                            "connection closed",
                            "接收循环已结束",
                            "ConnectionResetError",
                            "BrokenPipeError",
                            "OSError",
                            "timed out",
                        )
                    )
                    # 后端重启（连接被拒绝）视为 transient，给予更多重试机会
                    is_conn_refused = self.is_conn_refused(e)
                    if is_conn_refused:
                        is_transient = True
                    master_session_id = f"private_{str(getattr(session._cfg, 'master_qq_id', '') or '').strip()}"
                    is_master_session = bool(master_session_id and session.session_id == master_session_id)
                    if session._connection_state != "disconnected":
                        session._connection_state = "disconnected"
                        logger.error(f"[{session.session_id}] Connection failed (ws={ws_url}): {e}")
                    session.ws = None
                    if not session.adapter._conn_issue_notified.get(session.session_id, False):
                        try:
                            await session._notify_connection_issue(ws_url=ws_url, err=e)
                        except Exception:
                            pass
                    retry_count += 1
                    # 启动初期（60秒内）给予更多重试机会
                    startup_grace_period = 60.0
                    in_startup = (time.time() - session._start_time) < startup_grace_period
                    if is_transient:
                        max_retries = 30 if in_startup else 20
                    else:
                        max_retries = 15 if in_startup else 5
                    if retry_count > max_retries and not is_master_session:
                        logger.warning(f"[{session.session_id}] Too many failures ({retry_count}), stopping session.")
                        session.running = False
                        break
                    # 后端未启动（连接被拒绝）时使用固定短间隔重试，避免指数退避导致长时间无法重连
                    if is_conn_refused:
                        delay_s = 2.0
                    else:
                        delay_cap = 5.0 if is_master_session else 30.0
                        delay_s = min(delay_cap, 1.0 * (2 ** max(0, retry_count - 1)))
                    logger.info(
                        f"[{session.session_id}] Reconnecting in {delay_s:.1f}s (attempt {retry_count}/{max_retries}, transient={is_transient}, refused={is_conn_refused})"
                    )
                    await asyncio.sleep(delay_s)
        finally:
            # 连接循环退出时确保 running=False，让 monitor 能检测到并重启
            if session.running:
                session.running = False
                logger.warning(f"[{session.session_id}] Connection loop exited unexpectedly, marked as stopped.")
            current_session = session.adapter.sessions.get(session.session_id)
            if current_session is session:
                del session.adapter.sessions[session.session_id]

    def extract_host_port(self, ws_url: str):
        """从 ws_url 解析 host 和 port。"""
        try:
            from urllib.parse import urlparse

            p = urlparse(str(ws_url or "").strip())
            host = p.hostname
            port = p.port
            return host, port
        except Exception:
            return None, None

    def is_conn_refused(self, err: Exception) -> bool:
        """判断是否为连接拒绝错误。"""
        msg = str(err or "")
        if "WinError 1225" in msg:
            return True
        if "WinError 10061" in msg:
            return True
        if "Connection refused" in msg:
            return True
        if isinstance(err, (ConnectionRefusedError,)):
            return True
        return False

    def probe_tcp_port(self, host: str, port: int, timeout_s: float = 0.3) -> bool:
        """探测 TCP 端口是否开放。"""
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(max(0.05, float(timeout_s)))
            s.connect((host, int(port)))
            return True
        except Exception:
            return False
        finally:
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass

    async def notify_connection_issue(self, ws_url: str, err: Exception):
        """连接异常时向用户发送诊断提示（含端口探测）。"""
        session = self.session
        if not self.is_conn_refused(err):
            return

        # 后端短时重启属于正常波动，不要立刻对 QQ 用户报错。
        failure_grace_period = 20.0
        failure_since = float(getattr(session, "_connection_failure_since", 0.0) or 0.0)
        if failure_since <= 0.0:
            failure_since = time.time()
            session._connection_failure_since = failure_since
        elapsed = time.time() - failure_since
        if elapsed < failure_grace_period:
            remaining = failure_grace_period - elapsed
            logger.info(
                f"[{session.session_id}] 后端疑似正在重启（剩余 {remaining:.0f}s 宽限期），暂不报错"
            )
            return

        # 检查是否已经通知过（使用 adapter 层面的标志位）
        if session.adapter._conn_issue_notified.get(session.session_id, False):
            return

        host, port = self.extract_host_port(ws_url)
        if not host or not port:
            return

        is_loopback = host in {"127.0.0.1", "localhost"}
        port_open = await asyncio.to_thread(self.probe_tcp_port, host, int(port), 0.25)

        if is_loopback and not port_open:
            text = (
                "连接核心服务失败：本机未检测到 Xiaoyou Core 监听端口。\n"
                f"当前配置：{session._cfg.xiaoyou_ws_url}\n"
                "请先启动后端（运行 main.py 或 start_services.bat），再重试。"
            )
            await session.adapter.send_to_napcat(session.session_id, text)
            session.adapter._conn_issue_notified[session.session_id] = True
            return

        if port_open:
            text = (
                "连接核心服务失败：目标端口已打开，但 WS 握手失败。\n"
                f"当前配置：{session._cfg.xiaoyou_ws_url}\n"
                "请确认后端已启动且 WebSocket 路由为 /api/v1/ws。"
            )
            await session.adapter.send_to_napcat(session.session_id, text)
            session.adapter._conn_issue_notified[session.session_id] = True
            return

        text = (
            "连接核心服务失败：目标拒绝连接。\n"
            f"当前配置：{session._cfg.xiaoyou_ws_url}\n"
            "请检查后端地址/端口是否正确，以及防火墙/代理设置。"
        )
        await session.adapter.send_to_napcat(session.session_id, text)
        session.adapter._conn_issue_notified[session.session_id] = True
