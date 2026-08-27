"""快速测试 SiliconFlow Qwen3-VL-32B-Instruct 模型是否能用。

用法：
    d:\\AI\\xiaoyou-core\\venv_cpu\\Scripts\\python.exe tests\\scripts\\meme\\test_vl_model.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.logger import get_logger

logger = get_logger("test_vl_model")

# 测试图：normal/2/0.png
TEST_IMAGE = PROJECT_ROOT / "data" / "memes" / "normal" / "2" / "0.png"

# 两个 prompt 都测：一个简单、一个复杂（场景导向）
SIMPLE_PROMPT = "用一句话描述这张图片。"
SCENE_PROMPT = (
    "你是表情包语义分析专家。请分析图片并严格按以下格式输出：\n\n"
    "CAPTION: <先简述画面，再用\"常在...时使用\"句式说明适合的对话场景>\n"
    "TAGS: <3-8个关键词，顿号分隔>\n"
    "TEXT: <画面中的文字，无则写\"无\">\n"
)


def encode_image_b64(path: Path) -> str:
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


async def test_model(model_name: str, prompt: str, max_tokens: int = 200):
    """直接用 aiohttp 调 SiliconFlow API，绕开 client 封装，看原始响应。"""
    import aiohttp

    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        print("❌ 未设置 SILICONFLOW_API_KEY")
        return

    url = "https://api.siliconflow.cn/v1/chat/completions"
    data_url = encode_image_b64(TEST_IMAGE)
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print(f"\n{'='*60}")
    print(f"模型: {model_name}")
    print(f"Prompt: {prompt[:60]}...")
    print(f"图片: {TEST_IMAGE.name} (size={TEST_IMAGE.stat().st_size} bytes)")
    print(f"{'='*60}")

    try:
        async with aiohttp.ClientSession() as session:
            print(f"[{model_name}] 发送请求 (timeout=120s)...")
            try:
                async with session.post(
                    url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    print(f"[{model_name}] HTTP status: {resp.status}")
                    text = await resp.text()
                    if resp.status != 200:
                        print(f"[{model_name}] ❌ 失败响应: {text[:500]}")
                        return
                    data = json.loads(text)
                    if "choices" in data and len(data["choices"]) > 0:
                        content = data["choices"][0].get("message", {}).get("content", "")
                        print(f"[{model_name}] ✅ 成功:")
                        print("-" * 60)
                        print(content)
                        print("-" * 60)
                        usage = data.get("usage", {})
                        print(f"tokens: prompt={usage.get('prompt_tokens')}, "
                              f"completion={usage.get('completion_tokens')}")
                    else:
                        print(f"[{model_name}] ❌ 响应无 choices: {text[:500]}")
            except asyncio.TimeoutError:
                print(f"[{model_name}] ❌ 请求超时 (120s)")
            except Exception as e:
                print(f"[{model_name}] ❌ 请求异常: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"[{model_name}] ❌ session 异常: {type(e).__name__}: {e}")


async def main():
    if not TEST_IMAGE.is_file():
        print(f"❌ 测试图不存在: {TEST_IMAGE}")
        return

    # 测试 3 个模型：32B-Instruct（主用）、235B-Thinking（已禁用）、Qwen2.5-VL（备选）
    models = [
        ("Qwen/Qwen3-VL-32B-Instruct", SCENE_PROMPT),
        ("Qwen/Qwen3-VL-235B-A22B-Thinking", SIMPLE_PROMPT),  # 预期 403
        ("Qwen/Qwen2.5-VL-72B-Instruct", SCENE_PROMPT),  # 备选
    ]
    for model_name, prompt in models:
        await test_model(model_name, prompt)
        await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
