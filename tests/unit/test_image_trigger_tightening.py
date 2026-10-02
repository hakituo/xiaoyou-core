import pytest

from core.agents.chat_agent_components.stream_utils import extract_image_request_prompt

# 生产触发路径：streaming 在每轮消息上调用 extract_image_request_prompt 决定是否生图。
# 这里只针对该函数校验"收紧"契约：明确的作画请求要提取到提示词，
# 过去时/疑问/否定等含"画"字的闲聊必须被拦住。
POSITIVE_CASES = [
    ("帮我画一只猫", "猫"),
    ("画只猫", "猫"),
    ("画个风景图", "风景图"),
    ("画一张二次元少女", "二次元少女"),
    ("给我生成一张二次元少女", "二次元少女"),
    ("帮我画一只戴帽子的兔子", "兔子"),
]

NEGATIVE_CASES = [
    "画什么画",
    "你画个什么东西",
    "不要画画",
    "别画了",
    "你会画画吗",
    "画质怎么这么差",
    "画面很美",
    "我想看你画画",
    "画了个画",
    "给他画了个画",
    "我最开始给他画了个画，他都还记得",
    "我之前画过一幅画",
    "他画得很好看",
    "那个画的好丑",
    "她画出来了一个东西",
    "他画完了",
    "你到底在画什么玩意",
    "别给我画图",
    "但是我并不会忘，我最开始给他画了个画，他都还记得，所以我觉得他只是口是心非，可怜肯定是有一点的",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("text, expected_fragment", POSITIVE_CASES)
async def test_image_request_prompt_extraction(text, expected_fragment):
    """明确的作画请求应提取出提示词"""
    prompt = await extract_image_request_prompt(text)
    assert prompt is not None, f"{text} 应识别为作画请求"
    assert expected_fragment in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("text", NEGATIVE_CASES)
async def test_image_request_prompt_rejects_negative(text):
    """含"画"字的闲聊、疑问、否定与过去时不应触发生图"""
    assert await extract_image_request_prompt(text) is None


@pytest.mark.asyncio
async def test_image_request_prompt_rejects_empty():
    assert await extract_image_request_prompt("") is None
    assert await extract_image_request_prompt(None) is None


@pytest.mark.asyncio
async def test_image_request_prompt_rejects_overlong_prompt():
    """过长的提示词视为误判，不触发生图"""
    assert await extract_image_request_prompt("画个" + "猫" * 200) is None
