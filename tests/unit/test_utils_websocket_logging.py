"""core/utils/websocket_logging.py 单元测试。

覆盖两件事：
1. ``_find_windows_error`` 沿 ``__cause__`` / ``__context__`` 链查找 Windows 错误码，
   且必须能抵御自引用/成环的异常链（否则日志过滤器会死循环）。
2. ``RecoverableWebSocketDisconnectFilter`` 只对"data transfer failed + WinError 121"
   这一种组合做降级，其余记录一律原样放行。
"""

from __future__ import annotations

import logging

from core.utils.websocket_logging import (
    RecoverableWebSocketDisconnectFilter,
    _find_windows_error,
)

_TARGET_MESSAGE = "data transfer failed"
_DOWNGRADED_MESSAGE = "WebSocket 客户端读取超时（WinError 121），连接已清理并等待客户端重连"


class _WinError(Exception):
    """带 ``winerror`` 属性的异常，模拟 OSError / WinError。"""

    def __init__(self, winerror):
        super().__init__(f"winerror={winerror}")
        self.winerror = winerror


def _make_record(msg=_TARGET_MESSAGE, exc_info=None, level=logging.ERROR):
    """构造一条真实的 LogRecord（不用 MagicMock，确保 getMessage 行为真实）。"""
    return logging.LogRecord(
        name="uvicorn.error",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )


class TestFindWindowsError:
    """沿异常链查找错误码。"""

    def test_none_error_returns_false(self):
        assert _find_windows_error(None, 121) is False

    def test_direct_match(self):
        assert _find_windows_error(_WinError(121), 121) is True

    def test_other_code_returns_false(self):
        assert _find_windows_error(_WinError(10054), 121) is False

    def test_exception_without_winerror_returns_false(self):
        assert _find_windows_error(ValueError("no winerror"), 121) is False

    def test_match_through_cause_chain(self):
        outer = Exception("wrapped")
        outer.__cause__ = _WinError(121)
        assert _find_windows_error(outer, 121) is True

    def test_match_through_context_chain(self):
        outer = Exception("wrapped")
        outer.__context__ = _WinError(121)
        assert _find_windows_error(outer, 121) is True

    def test_cause_takes_precedence_over_context(self):
        """``current.__cause__ or current.__context__``：有 cause 时不再看 context。

        这条钉住的是既有语义（不是我们新引入的），将来若有人想改成"两条链都查"，
        这里会失败并提醒他这是行为变更。
        """
        outer = Exception("wrapped")
        outer.__cause__ = _WinError(10054)  # 不匹配
        outer.__context__ = _WinError(121)  # 匹配，但不会被走到
        assert _find_windows_error(outer, 121) is False

    def test_deep_chain_matches_last_node(self):
        node = _WinError(121)
        for _ in range(5):
            outer = _WinError(10054)
            outer.__cause__ = node
            node = outer
        assert _find_windows_error(node, 121) is True

    def test_self_referencing_chain_terminates(self):
        """自引用异常链必须靠 seen 集合跳出，不能死循环。"""
        err = _WinError(10054)
        err.__cause__ = err
        assert _find_windows_error(err, 121) is False

    def test_two_node_cycle_terminates(self):
        a = _WinError(10054)
        b = _WinError(10054)
        a.__cause__ = b
        b.__cause__ = a
        assert _find_windows_error(a, 121) is False


class TestRecoverableWebSocketDisconnectFilter:
    """过滤器只降级一种记录，其余原样放行。"""

    def setup_method(self):
        self.flt = RecoverableWebSocketDisconnectFilter()

    def test_is_a_logging_filter(self):
        assert isinstance(self.flt, logging.Filter)

    def test_already_marked_record_passes_untouched(self):
        """已标记的记录直接早返回——保证过滤器可重复施加而不反复改写。"""
        record = _make_record()
        record.recoverable_websocket_disconnect = True
        assert self.flt.filter(record) is True
        assert record.levelno == logging.ERROR
        assert record.msg == _TARGET_MESSAGE

    def test_unrelated_message_passes_untouched(self):
        record = _make_record(msg="some other error")
        assert self.flt.filter(record) is True
        assert record.levelno == logging.ERROR
        assert record.msg == "some other error"

    def test_target_message_without_exc_info_passes_untouched(self):
        record = _make_record(exc_info=None)
        assert self.flt.filter(record) is True
        assert record.levelno == logging.ERROR
        assert record.msg == _TARGET_MESSAGE

    def test_target_message_with_other_winerror_passes_untouched(self):
        err = _WinError(10054)
        record = _make_record(exc_info=(type(err), err, None))
        assert self.flt.filter(record) is True
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None

    def test_winerror_121_is_downgraded_to_stackless_info(self):
        err = _WinError(121)
        record = _make_record(exc_info=(type(err), err, None))
        # 预先塞入堆栈相关字段，验证它们被一并清空
        record.exc_text = "Traceback (most recent call last): ..."
        record.stack_info = "Stack (most recent call last): ..."

        assert self.flt.filter(record) is True

        assert record.levelno == logging.INFO
        assert record.levelname == "INFO"
        assert record.msg == _DOWNGRADED_MESSAGE
        assert record.args == ()
        assert record.exc_info is None
        assert record.exc_text is None
        assert record.stack_info is None
        assert record.recoverable_websocket_disconnect is True

    def test_downgrade_is_idempotent(self):
        err = _WinError(121)
        record = _make_record(exc_info=(type(err), err, None))
        assert self.flt.filter(record) is True
        # 第二次走"已标记"早返回分支，不会把 msg 再包一层
        assert self.flt.filter(record) is True
        assert record.levelno == logging.INFO
        assert record.msg == _DOWNGRADED_MESSAGE

    def test_nested_exception_chain_is_downgraded(self):
        """WinError 121 藏在 cause 链深处时同样应被识别。"""
        inner = _WinError(121)
        outer = Exception("connection lost")
        outer.__cause__ = inner
        record = _make_record(exc_info=(type(outer), outer, None))
        assert self.flt.filter(record) is True
        assert record.levelno == logging.INFO

    def test_real_logger_emits_downgraded_record(self):
        """端到端：挂到真实 logger 上，``exc_info=True`` 的记录被降级且不带堆栈。"""
        logger = logging.getLogger("tests.unit.websocket_logging.e2e")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        captured = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record):  # noqa: D102 - 测试用最小处理器
                captured.append(record)

        handler = _CaptureHandler()
        flt = RecoverableWebSocketDisconnectFilter()
        logger.addHandler(handler)
        logger.addFilter(flt)
        try:
            try:
                raise _WinError(121)
            except _WinError:
                logger.error(_TARGET_MESSAGE, exc_info=True)
        finally:
            logger.removeHandler(handler)
            logger.removeFilter(flt)

        assert len(captured) == 1
        emitted = captured[0]
        assert emitted.levelno == logging.INFO
        assert emitted.exc_info is None
        assert emitted.getMessage() == _DOWNGRADED_MESSAGE

    def test_real_logger_keeps_unrelated_record(self):
        """对照组：普通错误记录不被改写。"""
        logger = logging.getLogger("tests.unit.websocket_logging.e2e.control")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        captured = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record):  # noqa: D102 - 测试用最小处理器
                captured.append(record)

        handler = _CaptureHandler()
        flt = RecoverableWebSocketDisconnectFilter()
        logger.addHandler(handler)
        logger.addFilter(flt)
        try:
            logger.error("data transfer failed")
        finally:
            logger.removeHandler(handler)
            logger.removeFilter(flt)

        assert len(captured) == 1
        assert captured[0].levelno == logging.ERROR
        assert not getattr(captured[0], "recoverable_websocket_disconnect", False)
