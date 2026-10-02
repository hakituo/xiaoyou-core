#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证「按 provider 自动注入 prompt caching 标记」

口径来自 OpenRouter 官方文档 https://openrouter.ai/docs/guides/best-practices/prompt-caching ：
- 自动生效（不能塞标记）：OpenAI / DeepSeek / Grok / Moonshot / Groq / Z.AI / Gemini 隐式缓存
- Anthropic：请求级 cache_control（自动缓存，多轮对话推荐）
- Google Gemini：块级 cache_control（OpenRouter 只取最后一个断点）
- Alibaba Qwen：块级 cache_control，仅白名单模型

本脚本校验：
1. 判定表与文档口径一致（含 cloud: 前缀、直连厂商防误伤、TTL 只允许 5m/1h）
2. 已注册的 OpenRouter 模型逐一给出决策，且不会出现未知风格
3. 断点落在静态 system 与倒数第二条，动态尾巴（最后一条 user）不被标记
4. 所有 OpenRouter 请求都带 session_id（sticky routing 从第一条就生效）
5. 直连 provider（deepseek / zhipu / minimax / ark / aveline）的 payload 一字不改
6. 客户端已接线（_build_payload 调用 apply_cache_markers）

用法（在项目根目录用 venv_core 运行）：
    venv_core\\python.exe tests\\scripts\\llm\\verify_prompt_cache_markers.py

退出码：0=全部通过；非0=有检查项失败。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [OK] {message}")
    else:
        print(f"  [FAIL] {message}")
        failures.append(message)


def main() -> int:
    from config.settings_model import PROVIDER_BASE_URLS, PROVIDER_DEFAULT_MODELS
    from core.llm.openai_compat.cache_markers import (
        STYLE_BLOCK,
        STYLE_NONE,
        STYLE_TOP_LEVEL,
        apply_cache_markers,
        mark_cache_breakpoints,
        resolve_cache_strategy,
    )

    openrouter_url = PROVIDER_BASE_URLS.get("openrouter") or ""
    print(f"[1] OpenRouter base_url = {openrouter_url}")
    check(bool(openrouter_url), "config 里已注册 openrouter base_url")

    print("\n[2] 判定表（OpenRouter 文档口径）")
    expected = [
        ("anthropic/claude-opus-4.6", STYLE_TOP_LEVEL),
        ("google/gemini-3.8-flash", STYLE_BLOCK),
        ("qwen/qwen3-max", STYLE_BLOCK),
        ("deepseek/deepseek-v3.2", STYLE_BLOCK),
        ("deepseek/deepseek-v4-flash", STYLE_NONE),
        ("x-ai/grok-4.20", STYLE_NONE),
        ("moonshotai/kimi-k2.6", STYLE_NONE),
        ("openai/gpt-5.6", STYLE_NONE),
        ("minimax/minimax-m3:free", STYLE_NONE),
    ]
    for model, want in expected:
        got = resolve_cache_strategy(openrouter_url, model).style
        check(got == want, f"{model} -> {want}（实际 {got}）")

    print("\n[3] cloud: 前缀与直连厂商")
    check(
        resolve_cache_strategy(openrouter_url, "cloud:openrouter:anthropic/claude-opus-4.6").style
        == STYLE_TOP_LEVEL,
        "cloud:openrouter: 前缀仍能识别 anthropic",
    )
    for provider in ("deepseek", "zhipu", "minimax", "ark", "aveline"):
        base_url = PROVIDER_BASE_URLS.get(provider) or ""
        strategy = resolve_cache_strategy(base_url, "anthropic/claude-opus-4.6")
        check(strategy.style == STYLE_NONE, f"直连 {provider} 不注入标记（{strategy.reason}）")

    print("\n[4] TTL：Anthropic 默认 1 小时，其余上游固定 5 分钟")
    check(resolve_cache_strategy(openrouter_url, "anthropic/claude-opus-4.6").ttl == "1h",
          "Anthropic 默认 1h（多角色轮流对话不重写缓存）")
    check(resolve_cache_strategy(openrouter_url, "anthropic/claude-opus-4.6", ttl="5m").ttl == "",
          "可显式退回 5m")
    check(resolve_cache_strategy(openrouter_url, "anthropic/claude-opus-4.6", ttl="30m").ttl == "",
          "未知 TTL 退化为 5 分钟")
    check(resolve_cache_strategy(openrouter_url, "google/gemini-3.8-flash").ttl == "",
          "Gemini 保持 5 分钟（上游固定且不刷新）")
    check(resolve_cache_strategy(openrouter_url, "qwen/qwen3-max").ttl == "",
          "Alibaba Qwen 保持 5 分钟")

    print("\n[5] 已注册 OpenRouter 模型的决策")
    known = {STYLE_TOP_LEVEL, STYLE_BLOCK, STYLE_NONE}
    for model in PROVIDER_DEFAULT_MODELS.get("openrouter", []):
        strategy = resolve_cache_strategy(openrouter_url, model)
        check(strategy.style in known, f"{model} -> {strategy.style}（{strategy.reason}）")

    print("\n[6] 断点落点（静态 system + 倒数第二条，动态尾巴不碰）")
    messages = [
        {"role": "system", "content": "你是玲，一个静态人设"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗨"},
        {"role": "user", "content": "当前时间：2026-09-19 07:00\n\n【用户消息】\n在吗"},
    ]
    marked = mark_cache_breakpoints(messages)
    marked_count = sum(
        1
        for msg in marked
        if isinstance(msg.get("content"), list)
        and any("cache_control" in b for b in msg["content"] if isinstance(b, dict))
    )
    check(marked_count == 2, f"共 2 条消息被打点（实际 {marked_count}）")
    check(marked[0]["content"][-1].get("cache_control") == {"type": "ephemeral"},
          "首条 system 末尾块带 cache_control")
    check(marked[-1] == messages[-1], "最后一条（当前时间/环境/记忆/用户消息）保持原样")

    print("\n[7] payload 注入效果")
    anthropic_payload = {"model": "anthropic/claude-opus-4.6", "messages": messages}
    apply_cache_markers(anthropic_payload, base_url=openrouter_url)
    check(anthropic_payload.get("cache_control") == {"type": "ephemeral", "ttl": "1h"},
          "Anthropic 写请求级 cache_control（默认 1h TTL）")
    check(bool(anthropic_payload.get("session_id")), "Anthropic 带 session_id")
    check(anthropic_payload["messages"] == messages, "自动缓存模式不改消息本体")

    gemini_payload = {"model": "google/gemini-3.8-flash", "messages": messages}
    apply_cache_markers(gemini_payload, base_url=openrouter_url)
    check("cache_control" not in gemini_payload, "Gemini 不写请求级字段")
    check(isinstance(gemini_payload["messages"][0]["content"], list), "Gemini 走块级断点")

    deepseek_payload = {"model": "deepseek/deepseek-v4-flash", "messages": messages}
    apply_cache_markers(deepseek_payload, base_url=openrouter_url)
    check("cache_control" not in deepseek_payload, "自动缓存模型不写 cache_control")
    check(bool(deepseek_payload.get("session_id")), "自动缓存模型仍带 session_id（sticky routing）")

    direct_payload = {"model": "deepseek-v4-flash", "messages": messages}
    apply_cache_markers(direct_payload, base_url=PROVIDER_BASE_URLS.get("deepseek"))
    check(direct_payload == {"model": "deepseek-v4-flash", "messages": messages},
          "直连 DeepSeek 的 payload 一字不改")

    print("\n[8] 客户端接线")
    from core.llm.openai_compat import OpenAIClient

    client = OpenAIClient(api_key="k", base_url=openrouter_url, model="anthropic/claude-opus-4.6")
    payload = client._build_payload(messages, stream=True)
    check(payload.get("cache_control") == {"type": "ephemeral", "ttl": "1h"},
          "_build_payload 已注入标记（默认 1h TTL）")
    check(bool(payload.get("session_id")), "_build_payload 已注入 session_id")
    off = client._build_payload(messages, stream=True, cache_markers=False)
    check("cache_control" not in off, "cache_markers=False 可单次关闭")

    if failures:
        print(f"\n结果: {len(failures)} 项失败")
        return 1
    print("\n结果: prompt caching 标记按 provider 自动注入，契约全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
