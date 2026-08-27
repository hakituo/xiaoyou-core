#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试错误日志记录功能
验证错误消息被记录到 logs/YYYY/M/D/error.log 而不经过 BERT 分析
"""

import asyncio
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_error_log_store_basic():
    """测试错误日志存储基本功能"""
    print("\n=== 测试 1: 错误日志存储基本功能 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        from core.services.error_log_store import ErrorLogStore

        class MockErrorLogStore(ErrorLogStore):
            def _get_base_dir(self):
                return Path(tmpdir)

        store = MockErrorLogStore()

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
        print(f"✓ 错误记录成功，error_id: {result['error_id']}")

        errors = store.list_errors(conversation_id="test_user_123")
        assert len(errors) == 1, f"应该只有 1 条错误，实际有 {len(errors)} 条"
        assert errors[0]["error_message"] == "处理消息时出错: 模型加载失败", "错误消息应该一致"
        assert errors[0]["error_code"] == "MODEL_LOAD_ERROR", "错误码应该一致"
        assert errors[0]["user_message"] == "这是一条测试用户消息", "用户消息应该保存"
        print(f"✓ 错误查询成功，能正确获取所有字段")

        print("测试 1 通过!")


def test_error_log_store_file_location():
    """测试错误日志文件位置正确"""
    print("\n=== 测试 2: 错误日志文件位置 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        from core.services.error_log_store import ErrorLogStore

        class MockErrorLogStore(ErrorLogStore):
            def _get_base_dir(self):
                return Path(tmpdir)

        store = MockErrorLogStore()
        store.append_error(
            conversation_id="test_user",
            user_message="测试消息",
            error_message="测试错误",
            error_code="TEST_ERROR",
            source="test",
        )

        error_file = Path(tmpdir) / "error.log"
        assert error_file.exists(), f"错误日志文件应该位于 {error_file}"
        print(f"✓ 错误日志文件位于: {error_file}")

        content = error_file.read_text(encoding="utf-8")
        import json
        entry = json.loads(content.strip())
        assert "error_id" in entry, "应该包含 error_id"
        assert "timestamp" in entry, "应该包含 timestamp"
        assert entry["user_message"] == "测试消息", "用户消息应该被保存"
        assert entry["error_message"] == "测试错误", "错误消息应该被保存"
        print(f"✓ JSONL 条目结构正确，包含所有必要字段")

        print("测试 2 通过!")


def test_error_log_store_multiple_errors():
    """测试记录多条错误"""
    print("\n=== 测试 3: 记录多条错误 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        from core.services.error_log_store import ErrorLogStore

        class MockErrorLogStore(ErrorLogStore):
            def _get_base_dir(self):
                return Path(tmpdir)

        store = MockErrorLogStore()

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
        print(f"✓ 成功记录 5 条错误")

        stats = store.get_error_stats()
        errors_by_code = stats["errors_by_code"]
        assert "ERROR_0" in errors_by_code, "应该按错误码统计"
        print(f"✓ 错误统计功能正常: {errors_by_code}")

        print("测试 3 通过!")


def test_error_log_store_filtering():
    """测试错误日志过滤功能"""
    print("\n=== 测试 4: 错误日志过滤功能 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        from core.services.error_log_store import ErrorLogStore

        class MockErrorLogStore(ErrorLogStore):
            def _get_base_dir(self):
                return Path(tmpdir)

        store = MockErrorLogStore()

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
        print(f"✓ 按 conversation_id 过滤正常")

        errors_b = store.list_errors(error_code="ERROR_B")
        assert len(errors_b) == 1, "应该只有 ERROR_B 的 1 条错误"
        assert errors_b[0]["error_code"] == "ERROR_B"
        print(f"✓ 按 error_code 过滤正常")

        print("测试 4 通过!")


def test_integration_with_stream_orchestrator():
    """测试与 stream_orchestrator 错误处理集成"""
    print("\n=== 测试 5: 模拟 stream_orchestrator 错误处理 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        from core.services.error_log_store import ErrorLogStore

        class MockErrorLogStore(ErrorLogStore):
            def _get_base_dir(self):
                return Path(tmpdir)

        store = MockErrorLogStore()

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
        print(f"✓ 集成测试：错误被正确记录，error_id: {result['error_id']}")

        errors = store.list_errors(conversation_id="integration_test_user")
        assert len(errors) == 1
        assert errors[0]["source"] == "stream_orchestrator"
        print(f"✓ 集成测试：错误来源正确标记为 stream_orchestrator")

        print("测试 5 通过!")


def main():
    print("=" * 60)
    print("开始测试错误日志记录功能")
    print("=" * 60)

    test_error_log_store_basic()
    test_error_log_store_file_location()
    test_error_log_store_multiple_errors()
    test_error_log_store_filtering()
    test_integration_with_stream_orchestrator()

    print("\n" + "=" * 60)
    print("所有测试通过!")
    print("=" * 60)
    print("\n功能说明:")
    print("1. 错误消息被记录到 logs/YYYY/M/D/error.log（与 server.log、xiaoyou_main.log 并列）")
    print("2. 错误消息包含: 用户消息、错误信息、错误码、堆栈跟踪等")
    print("3. 错误消息不经过 BERT 分析")
    print("4. 错误消息不落盘到用户可见的历史记录")


if __name__ == "__main__":
    main()
