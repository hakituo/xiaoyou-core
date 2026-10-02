#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 OpenRouter 接入：gemini-3.8-flash、muse-spark 与免费聚合路由

通过项目自身的 OpenAIClient + OpenRouter 配置发起流式对话，校验：
1. .env 中 OPENROUTER_API_KEY 已配置
2. config.settings_model 已注册 openrouter provider（base_url / 默认模型列表）
3. 各模型能返回响应，并统计 TTFT（首 token 时延）与整轮耗时

用法（在项目根目录用 venv_core 运行）：
    venv_core\\python.exe tests\\scripts\\llm\\verify_openrouter_models.py

退出码：0=全部通过；非0=有模型调用失败。
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# 引入项目根目录与 .env
ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(ROOT, ".env"), override=True)

from config.settings_model import PROVIDER_BASE_URLS, PROVIDER_DEFAULT_MODELS  # noqa: E402
from core.llm.model_capabilities import is_vision_model  # noqa: E402
from core.llm.openai_compat import OpenAIClient  # noqa: E402

# 待验证的模型
MODELS = [
    "meta/muse-spark-1.3-contributor",
    "google/gemini-3.8-flash",
    "x-ai/grok-4.20",
    "openrouter/free",
    "anthropic/claude-opus-4.6",
]

# 简单测试提示词
SYSTEM_PROMPT = "你是连接测试助手，请尽量简洁，一句话即可。"
USER_PROMPT = "请只回复：连接成功"


async def test_one(client_factory, model: str) -> tuple:
    """流式发起一次对话，返回 (是否成功, ttft_ms, total_ms, 输出摘要/错误)。"""
    api_key, base_url, proxy = client_factory()
    client = OpenAIClient(api_key=api_key, base_url=base_url, model=model, proxy=proxy)
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ]
        ttft_ms = None
        t_total_start = time.perf_counter()
        parts = []
        error = None
        try:
            async for chunk in client.stream_chat(messages, temperature=0.2, max_tokens=256):
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t_total_start) * 1000  # 首个块到达即 TTFT
                if isinstance(chunk, dict) and "error" in chunk:
                    error = str(chunk.get("details") or chunk.get("error"))[:300]
                    break
                if isinstance(chunk, dict) and chunk.get("content"):
                    parts.append(str(chunk["content"]))
        finally:
            await client.shutdown()
        total_ms = (time.perf_counter() - t_total_start) * 1000

        if error:
            return False, ttft_ms, total_ms, f"错误: {error}"

        text = "".join(parts).strip()
        # 有输出文本即视为连通（可能只有推理内容）
        if not text:
            return False, ttft_ms, total_ms, "流式结束但无有效输出"
        return True, ttft_ms, total_ms, text
    except Exception as e:  # 网络/解析异常统一捕获
        return False, None, None, f"调用异常: {type(e).__name__}: {e}"


async def main() -> int:
    failures = 0

    # 1. key 检查
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("[FAIL] .env 中未配置 OPENROUTER_API_KEY")
        return 1
    print(f"[OK] OPENROUTER_API_KEY 已配置（长度 {len(api_key)}）")

    # 2. provider 注册检查
    base_url = PROVIDER_BASE_URLS.get("openrouter")
    if not base_url:
        print("[FAIL] config.settings_model.PROVIDER_BASE_URLS 未注册 openrouter")
        return 1
    default_models = PROVIDER_DEFAULT_MODELS.get("openrouter", [])
    print(f"[OK] openrouter provider 已注册: base_url={base_url}")
    print(f"[OK] 默认模型列表: {default_models}")

    model_proxy = os.getenv("OPENROUTER_PROXY_URL") or os.getenv("TELEGRAM_PROXY_URL") or None
    if model_proxy:
        print(f"[OK] 将经代理访问: {model_proxy}（用于绕过模型地区限制）")
    else:
        print("[WARN] 未检测到代理环境变量（OPENROUTER_PROXY_URL / TELEGRAM_PROXY_URL），可能遇地区限制")

    def _client_factory():
        return api_key, base_url, model_proxy

    # 3. 逐模型流式验证 + TTFT
    print(f"\n{'模型':<38}{'TTFT(ms)':>10}{'总耗时(ms)':>12}{'多模态':>8}  结果")
    results = []
    for model in MODELS:
        ok, ttft_ms, total_ms, summary = await test_one(_client_factory, model)
        # 429 上游限流（免费共享池常见）：等待后自动重试一次
        if not ok and ("429" in summary or "rate" in summary.lower()):
            print(f"  ({model} 上游限流，等待重试…)")
            await asyncio.sleep(6)
            ok, ttft_ms, total_ms, summary = await test_one(_client_factory, model)
        results.append((model, ok, ttft_ms, total_ms))
        ttft_str = f"{ttft_ms:.0f}" if ttft_ms is not None else "-"
        total_str = f"{total_ms:.0f}" if total_ms is not None else "-"
        vision_flag = "是" if is_vision_model(model) else "否"
        if ok:
            print(f"{model:<38}{ttft_str:>10}{total_str:>12}{vision_flag:>8}  成功: {summary[:40]}")
        else:
            print(f"{model:<38}{ttft_str:>10}{total_str:>12}{vision_flag:>8}  FAIL: {summary}")
            failures += 1

    # 汇总
    if failures:
        print(f"\n汇总: 通过 {len(MODELS) - failures}/{len(MODELS)}，存在 {failures} 个模型失败")
        return 1
    print("\n汇总: 全部通过（%d/%d 模型连接成功）" % (len(MODELS), len(MODELS)))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
