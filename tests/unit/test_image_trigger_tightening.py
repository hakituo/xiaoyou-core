import pytest
from core.trm_adapter import get_trm_adapter
from core.agents.chat_agent_components.streaming import _extract_image_request_prompt

@pytest.mark.asyncio
@pytest.mark.parametrize("text, expected", [
    ("帮我画一只猫", True),
    ("画个风景图", True),
    ("给我生成一张二次元少女", True),
    ("画什么画", False),
    ("你画个什么东西", False),
    ("不要画画", False),
    ("别画了", False),
    ("你会画画吗", False),
    ("画质怎么这么差", False),
    ("画面很美", False),
    ("我想看你画画", False),
    ("画了个画", False),
    ("给他画了个画", False),
    ("我最开始给他画了个画，他都还记得", False),
    ("我之前画过一幅画", False),
    ("他画得很好看", False),
    ("那个画的好丑", False),
    ("她画出来了一个东西", False),
    ("他画完了", False),
])
async def test_image_query_intent_tightening(text, expected):
    """验证语义层面的图像生成意图识别是否收紧 (异步版)"""
    adapter = get_trm_adapter()
    is_gen, _ = await adapter._detect_image_generation_intent(text)
    assert is_gen == expected

@pytest.mark.asyncio
async def test_streaming_prompt_extraction_tightening():
    """验证流式处理中的提示词提取逻辑是否过滤了负面输入"""
    assert await _extract_image_request_prompt("画什么画") is None
    assert await _extract_image_request_prompt("你到底在画什么玩意") is None
    assert await _extract_image_request_prompt("别给我画图") is None
    assert await _extract_image_request_prompt("画了个画") is None
    assert await _extract_image_request_prompt("给他画了个画，他都还记得") is None
    assert await _extract_image_request_prompt("我之前画过一幅画") is None
    assert await _extract_image_request_prompt("他画得很好看") is None
    assert await _extract_image_request_prompt("那个画的好丑") is None
    assert await _extract_image_request_prompt("她画出来了一个东西") is None
    assert await _extract_image_request_prompt("他画完了") is None
    assert await _extract_image_request_prompt("但是我并不会忘，我最开始给他画了个画，他都还记得，所以我觉得他只是口是心非，可怜肯定是有一点的") is None

    prompt = await _extract_image_request_prompt("帮我画一只戴帽子的兔子")
    assert prompt is not None
    assert "兔子" in prompt

    prompt = await _extract_image_request_prompt("画个风景图")
    assert prompt is not None

    prompt = await _extract_image_request_prompt("画一只猫")
    assert prompt is not None
    assert "猫" in prompt
