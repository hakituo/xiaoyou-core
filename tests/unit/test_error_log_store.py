#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试错误日志记录功能

验证错误消息被记录到 logs/YYYY/M/D/error.log（不经过 BERT 分析），
且写入与查询共用同一个日志根，便于整体重定向存储位置。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_store(tmpdir):
    """构造一个把日志根重定向到临时目录的 ErrorLogStore"""
    from core.services.error_log_store import ErrorLogStore

    class _RedirectedErrorLogStore(ErrorLogStore):
        def _get_logs_root(self):
            return Path(tmpdir)

    return _RedirectedErrorLogStore()


def test_error_log_store_basic():
    """测试错误日志存储基本功能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)

        result = store.append_error(
            conversation_id="test_user_123",
            user_message="这是一条测试用户消息",
            error_message="处理消息时出错: 模型加载失败",
            error_code="MODEL_LOAD_ERROR",
            error_details={"model": "gpt-4", "retry_count": 3},
            model_hint="cloud:openai:gpt-4",
            message_id="msg_12345",
            stack_trace="Traceback (most recent call last):\n  File 'test.py', line 10, in <module>\n    raise RuntimeError('模型加载失败')",
            source="test",
        )

        assert "error_id" in result, "应该返回 error_id"
        assert result["conversation_id"] == "test_user_123", "conversation_id 应该一致"

        errors = store.list_errors(conversation_id="test_user_123")
        assert len(errors) == 1, f"应该只有 1 条错误，实际有 {len(errors)} 条"
        assert errors[0]["error_message"] == "处理消息时出错: 模型加载失败", "错误消息应该一致"
        assert errors[0]["error_code"] == "MODEL_LOAD_ERROR", "错误码应该一致"
        assert errors[0]["user_message"] == "这是一条测试用户消息", "用户消息应该保存"
        assert errors[0]["error_details"] == {"model": "gpt-4", "retry_count": 3}, "错误详情应该保存"
        assert errors[0]["message_id"] == "msg_12345", "message_id 应该保存"


def test_error_log_store_file_location():
    """测试错误日志文件位置正确（logs/YYYY/M/D/error.log）"""
    from core.utils.time_utils import get_current_time

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        store.append_error(
            conversation_id="test_user",
            user_message="测试消息",
            error_message="测试错误",
            error_code="TEST_ERROR",
            source="test",
        )

        now = get_current_time()
        error_file = (
            Path(tmpdir) / str(now.year) / str(now.month) / str(now.day) / "error.log"
        )
        assert error_file.exists(), f"错误日志文件应该位于 {error_file}"

        entry = json.loads(error_file.read_text(encoding="utf-8").strip())
        assert "error_id" in entry, "应该包含 error_id"
        assert "timestamp" in entry, "应该包含 timestamp"
        assert entry["user_message"] == "测试消息", "用户消息应该被保存"
        assert entry["error_message"] == "测试错误", "错误消息应该被保存"
        assert entry["error_code"] == "TEST_ERROR", "错误码应该被保存"


def test_error_log_store_multiple_errors():
    """测试记录多条错误"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)

        for i in range(5):
            store.append_error(
                conversation_id="test_user_123",
                user_message=f"用户消息 {i}",
                error_message=f"错误 {i}",
                error_code=f"ERROR_{i}",
                source="test",
            )

        errors = store.list_errors(conversation_id="test_user_123")
        assert len(errors) == 5, f"应该有 5 条错误，实际有 {len(errors)} 条"

        stats = store.get_error_stats()
        errors_by_code = stats["errors_by_code"]
        assert errors_by_code.get("ERROR_0") == 1, "应该按错误码统计"
        assert stats["total_errors"] == 5, "统计总数应该等于已记录条数"


def test_error_log_store_filtering():
    """测试错误日志过滤功能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)

        store.append_error(
            conversation_id="user_A",
            user_message="用户A的消息",
            error_message="错误A",
            error_code="ERROR_A",
            source="test",
        )
        store.append_error(
            conversation_id="user_B",
            user_message="用户B的消息",
            error_message="错误B",
            error_code="ERROR_B",
            source="test",
        )

        errors_a = store.list_errors(conversation_id="user_A")
        assert len(errors_a) == 1, "应该只有 user_A 的 1 条错误"
        assert errors_a[0]["conversation_id"] == "user_A"

        errors_b = store.list_errors(error_code="ERROR_B")
        assert len(errors_b) == 1, "应该只有 ERROR_B 的 1 条错误"
        assert errors_b[0]["error_code"] == "ERROR_B"


def test_error_log_store_isolated_from_real_logs():
    """重定向日志根后，不应读到项目 logs 下的真实错误日志"""
    from core.services.error_log_store import ErrorLogStore

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        store.append_error(
            conversation_id="isolated_user",
            user_message="隔离测试",
            error_message="隔离错误",
            error_code="ISOLATED",
            source="test",
        )

        assert len(store.list_errors(conversation_id="isolated_user")) == 1
        assert isinstance(ErrorLogStore()._get_logs_root(), Path)
        assert store._get_logs_root() != ErrorLogStore()._get_logs_root()


def test_integration_with_stream_orchestrator():
    """测试与 stream_orchestrator 错误处理集成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)

        error_chunk = {
            "type": "error",
            "message": "处理消息时出错: 模型加载失败",
            "error_code": "MODEL_LOAD_ERROR",
            "details": {"error_type": "RuntimeError", "model": "test-model"},
        }

        result = store.append_error(
            conversation_id="integration_test_user",
            user_message="正常的用户消息",
            error_message=error_chunk.get("message"),
            error_code=error_chunk.get("error_code"),
            error_details=error_chunk.get("details"),
            model_hint="cloud:test:model",
            message_id="int_msg_123",
            source="stream_orchestrator",
        )

        assert "error_id" in result

        errors = store.list_errors(conversation_id="integration_test_user")
        assert len(errors) == 1
        assert errors[0]["source"] == "stream_orchestrator"
        assert errors[0]["error_details"] == {"error_type": "RuntimeError", "model": "test-model"}
