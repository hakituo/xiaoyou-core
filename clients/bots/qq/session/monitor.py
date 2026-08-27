"""主会话监控器。

从 QQAdapter 提取，负责监控和维持主会话连接。
"""
import asyncio
import time


class SessionMonitor:
    """主会话监控器，定期检查并重启失效的主会话。"""

    def __init__(self, adapter):
        self.adapter = adapter
        self.logger = adapter.logger

    async def monitor_master_session(self):
        self.logger.info("Starting Master Session Monitor...")
        while self.adapter.transport.running:
            try:
                await self._check_and_restart_master()
            except Exception as e:
                self.logger.error(f"Master session monitor error: {e}")
            await asyncio.sleep(30)

    async def _check_and_restart_master(self):
        mid = str(self.adapter.cfg.master_qq_id or "").strip()
        if not mid:
            return
        sid = f"private_{mid}"
        session = self.adapter.sessions.get(sid)

        needs_restart = False
        if not session:
            self.logger.info(f"Monitor: Master session '{sid}' missing. Creating...")
            needs_restart = True
        elif not getattr(session, "running", False):
            self.logger.info(f"Monitor: Master session '{sid}' stopped. Restarting...")
            needs_restart = True
        elif self._is_task_dead(session):
            # 连接循环 task 已结束但 running 标志仍为 True（异常退出）
            self.logger.warning(
                f"Monitor: Master session '{sid}' task is dead but running=True. Restarting..."
            )
            needs_restart = True
        elif session.ws is None or self._is_ws_closed(session):
            # ws 断开：快速重启（不等 120 秒超时），让连接循环尽快恢复
            is_sleeping = getattr(session, "_in_smart_sleep", False)
            # ws 刚断开时给予短宽限期（10 秒），让连接循环自行重连
            # 只有持续断开超过宽限期才干预
            disconnect_grace = 10.0 if not is_sleeping else 300.0
            last_connected = float(getattr(session, "_last_connected_at", 0.0) or 0.0)
            if last_connected > 0 and (time.time() - last_connected) < disconnect_grace:
                # 宽限期内，连接循环可能正在重连，不干预
                pass
            else:
                timeout = 1200 if is_sleeping else 120
                if time.time() - getattr(session, "last_activity", 0) > timeout:
                    self.logger.warning(
                        f"Monitor: Master session '{sid}' inactive for >{timeout}s "
                        f"(sleeping={is_sleeping}). Restarting..."
                    )
                    await session.stop()
                    needs_restart = True

        if needs_restart:
            if session:
                try:
                    await session.stop()
                except Exception:
                    pass
            from clients.bots.qq.session.session import XiaoyouSession
            new_session = XiaoyouSession(sid, self.adapter)
            self.adapter.sessions[sid] = new_session
            await new_session.start()
            self.logger.info(f"Monitor: Master session '{sid}' (re)started.")

    @staticmethod
    def _is_task_dead(session) -> bool:
        """检查连接循环 task 是否已结束但 running 仍为 True。"""
        task = getattr(session, "task", None)
        if task is None:
            return False
        return task.done() and getattr(session, "running", False)

    @staticmethod
    def _is_ws_closed(session) -> bool:
        """安全检查 WebSocket 是否已关闭。"""
        ws = getattr(session, "ws", None)
        if ws is None:
            return True
        closed_attr = getattr(ws, "closed", None)
        if closed_attr is None:
            # 非 websockets 库对象，尝试其他方式检测
            try:
                return bool(getattr(ws, "state", "") == "closed")
            except Exception:
                return False
        try:
            return bool(closed_attr)
        except Exception:
            return False

    async def ensure_master_private_session(self):
        """确保主会话存在并运行"""
        mid = str(self.adapter.cfg.master_qq_id or "").strip()
        if not mid or not mid.isdigit():
            return
        sid = f"private_{mid}"
        sess = self.adapter.sessions.get(sid)
        if not sess or not getattr(sess, "running", False):
            from clients.bots.qq.session.session import XiaoyouSession
            sess = XiaoyouSession(sid, self.adapter)
            self.adapter.sessions[sid] = sess
            await sess.start()
