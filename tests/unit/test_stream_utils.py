"""
流式工具模块单元测试

只覆盖仍在 streaming_pipeline 中被引用的能力：
- StreamContextBuilder：长回复意图检测与生成参数推断
- ParallelProcessor：生命统计提取与亲密度上下文

标签解析、JSON 流式解析与文本平滑已迁移到 streaming_pipeline，
其旧实现连同对应用例一并移除。
"""

import pytest

from core.agents.chat_agent_components.stream_utils import (
    ParallelProcessor,
    StreamContextBuilder,
)


class TestContextBuilder:
    """上下文构建器测试"""

    def test_detect_wants_long_by_keywords(self):
        assert StreamContextBuilder.detect_wants_long("详细解释一下")
        assert StreamContextBuilder.detect_wants_long("为什么会这样")
        assert StreamContextBuilder.detect_wants_long("我快崩溃了，安慰我一下")
        assert not StreamContextBuilder.detect_wants_long("你好")

    def test_detect_wants_long_empty_message(self):
        assert not StreamContextBuilder.detect_wants_long("")
        assert not StreamContextBuilder.detect_wants_long("   ")

    def test_detect_wants_long_by_bert_semantic(self, monkeypatch):
        class _FakeAnalyzer:
            def analyze_intent(self, content, candidates=None):
                return {
                    "intent": "EMOTIONAL_SUPPORT",
                    "confidence": 0.91,
                }

        monkeypatch.setattr(
            "core.services.data_ops.bert_analyzer.get_bert_analyzer",
            lambda: _FakeAnalyzer(),
        )
        assert StreamContextBuilder.detect_wants_long("我真的撑不住了")

    def test_detect_wants_long_ignores_low_confidence_bert(self, monkeypatch):
        class _FakeAnalyzer:
            def analyze_intent(self, content, candidates=None):
                return {"intent": "NONE", "confidence": 0.1}

        monkeypatch.setattr(
            "core.services.data_ops.bert_analyzer.get_bert_analyzer",
            lambda: _FakeAnalyzer(),
        )
        assert not StreamContextBuilder.detect_wants_long("随便说点什么吧")

    def test_infer_max_tokens_defaults_to_unlimited(self):
        """默认不限制输出长度，由模型自行决定"""
        assert (
            StreamContextBuilder.infer_max_tokens(
                "study", False, False, False, pref_length="normal"
            )
            is None
        )
        assert (
            StreamContextBuilder.infer_max_tokens(
                "chat", True, False, True, pref_length="long"
            )
            is None
        )

    def test_infer_max_tokens_respects_explicit_value(self):
        """调用方显式指定时原样返回"""
        assert (
            StreamContextBuilder.infer_max_tokens(
                "chat", False, False, False, pref_length="normal", max_tokens=512
            )
            == 512
        )

    def test_infer_soft_reply_limit(self):
        # 想要长回复
        assert (
            StreamContextBuilder.infer_soft_reply_limit("chat", True, False, "你好")
            == 1000
        )
        # 系统事件
        assert (
            StreamContextBuilder.infer_soft_reply_limit("chat", False, True, "你好")
            == 300
        )
        # 默认简短回复，与输入长度无关
        assert (
            StreamContextBuilder.infer_soft_reply_limit("chat", False, False, "你好")
            == 50
        )
        assert (
            StreamContextBuilder.infer_soft_reply_limit(
                "chat", False, False, "你好，今天天气怎么样，我想出去玩"
            )
            == 50
        )


class TestParallelProcessor:
    """并行处理器测试"""

    def test_extract_life_stats_defaults(self):
        mood, shyness, is_sick, immune_damage, level = (
            ParallelProcessor.extract_life_stats(None)
        )
        assert (mood, shyness, is_sick, immune_damage, level) == (
            0.5,
            0.1,
            False,
            0.0,
            1,
        )

    def test_extract_life_stats_values(self):
        stats = {
            "mood_score": 0.8,
            "shyness_score": 0.2,
            "is_sick": True,
            "immune_damage": 1.5,
            "level": 3,
        }
        assert ParallelProcessor.extract_life_stats(stats) == (0.8, 0.2, True, 1.5, 3)

    @pytest.mark.asyncio
    async def test_handle_intimacy_context(self):
        assert await ParallelProcessor.handle_intimacy_context("你好", 0.9) == 0.05
        assert await ParallelProcessor.handle_intimacy_context("你好", 0.1) == 0.3
        assert await ParallelProcessor.handle_intimacy_context("你好", 0.5) is None
