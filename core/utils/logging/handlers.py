"""日志文件 Handler 实现。

集中放置所有自定义文件 Handler：
- ``_SafeRotatingFileHandler`` / ``_SafeTimedRotatingFileHandler``：
  Windows 上对轮转失败（PermissionError 32，文件被锁定）做重试兜底。
- ``_CrossDayFileHandlerMixin`` 及其组合类：
  在跨天（本地日期变化）时自动切换到当日 ``logs/YYYY/M/D`` 目录，
  解决进程连续运行跨 0 点后日志写入旧日期目录的问题。
"""
import logging
import os
import sys
import shutil
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


def _report_rotation_failure(log_file: str, error: Exception):
    """日志轮转失败时，通过独立的 stderr logger 发出 ERROR，避免递归"""
    try:
        _rotation_logger = logging.getLogger("_rotation_failure")
        if not _rotation_logger.handlers:
            _rotation_logger.propagate = False
            _rotation_logger.setLevel(logging.ERROR)
            _rotation_logger.addHandler(logging.StreamHandler())
        _rotation_logger.error(
            "日志轮转失败 (file=%s): %s - 可能有其他进程/线程锁定了日志文件",
            log_file, error, exc_info=True,
        )
    except Exception:
        # 兜底：直接写 stderr
        import sys as _sys
        _sys.stderr.write(f"[CRITICAL] 日志轮转失败: {log_file} - {error}\n")


class _SafeRotatingFileHandler(RotatingFileHandler):
    """在 Windows 上对 doRollover 做重试，解决文件锁定导致的 PermissionError 32"""

    _MAX_RETRIES = 5
    _RETRY_DELAY = 0.5  # 秒

    def rotate(self, source, dest):
        """重写 rotate，Windows 上 os.rename 失败时用 copy+truncate 兜底"""
        try:
            os.rename(source, dest)
        except PermissionError:
            if sys.platform == "win32":
                # Windows: 文件被其他进程锁定时，copy 内容到目标再清空源文件
                try:
                    shutil.copy2(source, dest)
                    with open(source, "w", encoding="utf-8") as f:
                        f.truncate()
                    return
                except Exception:
                    raise
            raise

    def doRollover(self):
        if sys.platform == "win32":
            for attempt in range(self._MAX_RETRIES):
                try:
                    super().doRollover()
                    return
                except PermissionError as e:
                    if attempt < self._MAX_RETRIES - 1:
                        time.sleep(self._RETRY_DELAY)
                        continue
                    # 最后一次仍然失败，放弃滚动，重新打开文件继续写入
                    self._reopen_stream()
                    # 主动发一条 ERROR 日志，让 auto-heal 能捕获
                    _report_rotation_failure(self.baseFilename, e)
                    return
        else:
            super().doRollover()

    def _reopen_stream(self):
        """重新打开文件流，确保日志可以继续写入"""
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:
                pass
        # 重新以追加模式打开文件
        self.stream = self._open()


class _SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """在 Windows 上对 doRollover 做重试，解决文件锁定导致的 PermissionError 32"""

    _MAX_RETRIES = 5
    _RETRY_DELAY = 0.5

    def rotate(self, source, dest):
        """重写 rotate，Windows 上 os.rename 失败时用 copy+truncate 兜底"""
        try:
            os.rename(source, dest)
        except PermissionError:
            if sys.platform == "win32":
                try:
                    shutil.copy2(source, dest)
                    with open(source, "w", encoding="utf-8") as f:
                        f.truncate()
                    return
                except Exception:
                    raise
            raise

    def doRollover(self):
        if sys.platform == "win32":
            for attempt in range(self._MAX_RETRIES):
                try:
                    super().doRollover()
                    return
                except PermissionError as e:
                    if attempt < self._MAX_RETRIES - 1:
                        time.sleep(self._RETRY_DELAY)
                        continue
                    # 最后一次仍然失败，放弃滚动，重新打开文件继续写入
                    self._reopen_stream()
                    _report_rotation_failure(self.baseFilename, e)
                    return
        else:
            super().doRollover()

    def _reopen_stream(self):
        """重新打开文件流，确保日志可以继续写入"""
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:
                pass
        # 重新以追加模式打开文件
        self.stream = self._open()


class _CrossDayFileHandlerMixin:
    """Mixin：让文件 handler 在跨天（本地日期变化）时自动切换到当日日志目录。

    背景：日志目录按 ``logs/YYYY/M/D`` 分层，但 handler 的 baseFilename 在进程
    启动时一次性固定。若进程连续运行跨过 0 点，新一天的日志会被写进旧日期目录，
    导致按日期检索失效、日志越积越多（见 2026-08-13 日志误写入 8/12 目录问题）。

    该 mixin 在每次 emit 前检查当前本地日期目录是否与 baseFilename 所在目录一致，
    不一致则关闭旧流、新建当日目录、打开当日文件，实现无感知的跨天目录切换。
    """

    _cross_day_lock = threading.Lock()

    def _today_log_dir(self) -> str:
        """根据 baseFilename 的文件名，拼出当日日期目录下的完整路径。

        日志目录结构固定为 ``<root>/YYYY/M/D/<filename>``，
        因此从 baseFilename 回退 4 层（file→day→month→year→root）得到 <root>。
        """
        configured_root = getattr(self, "_daily_log_root", None)
        configured_relative = getattr(self, "_daily_relative_path", None)
        if configured_root and configured_relative:
            now = datetime.now()
            return os.path.join(
                configured_root,
                str(now.year),
                str(now.month),
                str(now.day),
                configured_relative,
            )

        base = str(self.baseFilename)
        filename = os.path.basename(base)
        root = base
        for _ in range(4):
            root = os.path.dirname(root)
        now = datetime.now()
        return os.path.join(
            root,
            str(now.year),
            str(now.month),
            str(now.day),
            filename,
        )

    def _cross_day_needs_switch(self) -> bool:
        today_path = self._today_log_dir()
        return os.path.dirname(today_path) != os.path.dirname(self.baseFilename)

    def _cross_day_switch(self) -> None:
        """切换到当日日志目录（线程安全）。失败则保持原文件继续写入。"""
        with self._cross_day_lock:
            try:
                today_path = self._today_log_dir()
                if os.path.dirname(today_path) == os.path.dirname(self.baseFilename):
                    return
                # 关闭旧流
                if self.stream is not None:
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                os.makedirs(os.path.dirname(today_path), exist_ok=True)
                self.baseFilename = today_path
                self.stream = self._open()
                index_writer = getattr(self, "_daily_index_writer", None)
                if callable(index_writer):
                    now = datetime.now()
                    daily_dir = os.path.join(
                        self._daily_log_root,
                        str(now.year),
                        str(now.month),
                        str(now.day),
                    )
                    index_writer(daily_dir)
            except Exception as e:  # noqa: BLE001
                # 切换失败不应中断日志；回退到原文件继续写
                try:
                    if self.stream is None or self.stream.closed:
                        self.stream = self._open()
                except Exception:
                    pass
                _report_rotation_failure(self.baseFilename, e)

    def emit(self, record):
        try:
            if self._cross_day_needs_switch():
                self._cross_day_switch()
        except Exception:
            pass
        return super().emit(record)


class _CrossDayRotatingFileHandler(_CrossDayFileHandlerMixin, _SafeRotatingFileHandler):
    """按 size 轮转 + 跨天目录自动切换的文件 handler。"""


class _CrossDayTimedRotatingFileHandler(_CrossDayFileHandlerMixin, _SafeTimedRotatingFileHandler):
    """按时间轮转 + 跨天目录自动切换的文件 handler。"""
