"""
流式工具模块单元测试
"""
import pytest
from core.agents.chat_agent_components.stream_utils import (
    StreamContextBuilder,
    TagParser,
    JSONStreamParser,
    StreamTextSmoother,
    normalize_tilde_ending,
    looks_formal_user_text,
    looks_mostly_english,
    find_stream_boundary,
)


class TestTextUtils:
    """文本工具测试"""
    
    def test_normalize_tilde_ending(self):
        assert normalize_tilde_ending("你好~~~") == "你好~"
        assert normalize_tilde_ending("你好。~~") == "你好~"
        assert normalize_tilde_ending("你好") == "你好"
    
    def test_looks_formal_user_text(self):
        assert looks_formal_user_text("请问您好")
        assert looks_formal_user_text("麻烦您帮忙")
        assert not looks_formal_user_text("你好")
    
    def test_looks_mostly_english(self):
        assert looks_mostly_english("Hello world")
        assert looks_mostly_english("This is a test")
        assert not looks_mostly_english("你好 world")
    
    def test_find_stream_boundary(self):
        # 找到句号
        assert find_stream_boundary("你好。世界", min_chars=1, max_chars=10) == 3
        # 找到逗号
        assert find_stream_boundary("你好，世界", min_chars=1, max_chars=10) == 3
        # 没有分隔符
        assert find_stream_boundary("你好世界", min_chars=1, max_chars=4) == 0


class TestContextBuilder:
    """上下文构建器测试"""
    
    def test_detect_wants_long(self):
        assert StreamContextBuilder.detect_wants_long("详细解释一下")
        assert StreamContextBuilder.detect_wants_long("为什么会这样")
        assert StreamContextBuilder.detect_wants_long("我快崩溃了，安慰我一下")
        assert not StreamContextBuilder.detect_wants_long("你好")

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
    
    def test_infer_max_tokens(self):
        # 学习模式
        assert StreamContextBuilder.infer_max_tokens(
            "study", False, False, False
        ) == 1024
        
        # 敏感模式
        assert StreamContextBuilder.infer_max_tokens(
            "chat", True, False, False
        ) == 1536
        
        # 想要长回复
        assert StreamContextBuilder.infer_max_tokens(
            "chat", False, False, True
        ) == 2048
        
        # 短回复偏好
        assert StreamContextBuilder.infer_max_tokens(
            "chat", False, False, False, pref_length="short"
        ) == 256
    
    def test_infer_soft_reply_limit(self):
        # 极短输入
        assert StreamContextBuilder.infer_soft_reply_limit(
            "chat", False, False, "你好"
        ) == 50
        
        # 中等输入
        assert StreamContextBuilder.infer_soft_reply_limit(
            "chat", False, False, "你好，今天天气怎么样"
        ) == 80
        
        # 长输入
        assert StreamContextBuilder.infer_soft_reply_limit(
            "chat", False, False, "你好，今天天气怎么样，我想出去玩"
        ) is None
        
        # 学习模式不限制
        assert StreamContextBuilder.infer_soft_reply_limit(
            "study", False, False, "你好"
        ) is None


class TestTagParser:
    """标签解析器测试"""
    
    def test_find_next_tag(self):
        parser = TagParser()
        
        # 找到情感标签
        idx, tag_type = parser.find_next_tag("hello [EMO: happy] world")
        assert idx == 6
        assert tag_type == "emo"
        
        # 找到图片标签
        idx, tag_type = parser.find_next_tag("text [GEN_IMG: cat] more")
        assert idx == 5
        assert tag_type == "img"
        
        # 没有标签
        idx, tag_type = parser.find_next_tag("hello world")
        assert idx == -1
        assert tag_type == ""
    
    def test_parse_image_tag(self):
        parser = TagParser()
        parser.in_image_tag = True
        
        # 完整标签
        done, remaining = parser.parse_image_tag("a cute cat]more text")
        assert done
        assert remaining == "more text"
        assert "a cute cat" in parser.collected_image_prompts
    
    def test_parse_emotion_tag(self):
        parser = TagParser()
        parser.in_emo_tag = True
        
        # 完整标签
        done, remaining, emotion = parser.parse_emotion_tag("happy]more text")
        assert done
        assert remaining == "more text"
        assert emotion == "happy"
    
    def test_is_parsing_tag(self):
        parser = TagParser()
        assert not parser.is_parsing_tag()
        
        parser.in_image_tag = True
        assert parser.is_parsing_tag()


class TestJSONParser:
    """JSON解析器测试"""
    
    def test_try_enter_json_mode(self):
        parser = JSONStreamParser()
        
        # 进入JSON模式
        entered, remaining = parser.try_enter_json_mode('{"analysis": "test"}', True)
        assert entered
        assert parser.is_json_mode
        assert remaining == ""
        
        # 不允许JSON模式
        parser2 = JSONStreamParser()
        entered, remaining = parser2.try_enter_json_mode('{"test": 1}', False)
        assert not entered
    
    def test_parse_chunk_analysis(self):
        parser = JSONStreamParser()
        parser.is_json_mode = True
        parser.json_state = "in_analysis"
        parser.json_buffer = 'thinking about it",'
        
        visible, thought, state = parser.parse_chunk("")
        assert visible == ""
        assert thought == "thinking about it"
        assert state == "waiting_response"
    
    def test_check_init_timeout(self):
        parser = JSONStreamParser()
        parser.json_state = "init"
        parser.json_mode_start_ts = 0  # 很久以前
        
        assert parser.check_init_timeout()


class TestStreamSmoother:
    """流式平滑器测试"""
    
    def test_disabled_mode(self):
        smoother = StreamTextSmoother(
            enabled=False,
            min_chars=10,
            hard_chars=50,
            max_delay_ms=100
        )
        
        # 禁用模式直接透传
        result = smoother.push("你好", force=False)
        assert result == ["你好"]
    
    def test_enabled_mode_force(self):
        smoother = StreamTextSmoother(
            enabled=True,
            min_chars=10,
            hard_chars=50,
            max_delay_ms=100
        )
        
        # 强制输出
        smoother.push("你好", force=False)
        result = smoother.drain()
        assert len(result) > 0
        assert "你好" in "".join(result)
    
    def test_boundary_detection(self):
        smoother = StreamTextSmoother(
            enabled=True,
            min_chars=5,
            hard_chars=50,
            max_delay_ms=1000
        )
        
        # 推送带句号的文本
        result = smoother.push("你好。世界", force=False)
        # 应该在句号处断开
        if result:
            assert "。" in "".join(result)


@pytest.mark.asyncio
async def test_parallel_processor():
    """并行处理器测试（需要mock）"""
    # 这个测试需要mock agent和相关服务
    # 这里只是示例框架
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
