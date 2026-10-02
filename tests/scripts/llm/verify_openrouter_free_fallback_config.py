#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证后台任务直接使用 MiniMax 官方 M3，OpenRouter 免费模型仅保留手动兜底

检查点：
1. Active Care、日记、自愈、记忆蒸馏、角色日常都直接使用 MiniMax 官方 M3
2. 不配置 Active Care 二次回退，手动 OpenRouter 免费模型仍可回退到官方 M3
3. provider 默认模型列表不再注册具体 :free 型号
4. cloud_router 能识别聚合入口和旧版具体免费型号
5. 免费路由失败或只返回 reasoning 时均返回 MiniMax 官方 M3 兜底客户端

用法：
    venv_core\\python.exe tests\\scripts\\llm\\verify_openrouter_free_fallback_config.py

退出码：0=通过；非0=任一检查失败。
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)

# 诊断统一走 stderr，规避部分核心模块对 stdout 的重定向
def _out(msg: str):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def check() -> int:
    failures = 0

    def _fail(msg: str):
        nonlocal failures
        failures += 1
        _out(f"[FAIL] {msg}")

    free = "cloud:openrouter:openrouter/free"
    official_m3 = "cloud:minimax:MiniMax-M3"
    legacy_free_m3 = "cloud:openrouter:minimax/minimax-m3:free"

    # 1. yaml 里的 fallback_models 配置
    yaml_text = Path(ROOT, "config", "yaml", "sections", "model_routing.yaml").read_text(
        encoding="utf-8"
    )
    fb_start = yaml_text.find("fallback_models:")
    fb_end = yaml_text.find("auto_heal_models:", fb_start)
    fb_blk = yaml_text[fb_start:fb_end if fb_end > 0 else len(yaml_text)]
    expect = {"openrouter_free": official_m3}
    for key, want in expect.items():
        line = next(
            (ln for ln in fb_blk.splitlines() if ln.strip().startswith(f"{key}:")), ""
        )
        if want not in line:
            _fail(f"fallback_models.{key} 未指向预期模型 {want!r}: {line.strip()!r}")
    # 2. model_config getter 返回值
    sys.path.insert(0, str(ROOT))
    from config.model_config import (
        get_fallback_model_for_active_care,
        get_fallback_model_for_openrouter_free,
    )

    for name, val, want in [
        ("get_fallback_model_for_active_care()", get_fallback_model_for_active_care(), ""),
        ("get_fallback_model_for_openrouter_free()", get_fallback_model_for_openrouter_free(), official_m3),
    ]:
        if val != want:
            _fail(f"{name} 应返回 {want!r}，实际 {val!r}")

    # 3. 所有后台路由直接使用官方 M3
    from config.model_config import load_model_config
    from config.settings_model import PROVIDER_DEFAULT_MODELS

    routing = load_model_config()
    active_care = routing.get("active_care_models", {})
    content_generation = active_care.get("content_generation", {})
    routed_models = {
        "active_care.default": content_generation.get("default"),
        "active_care.ling": content_generation.get("ling"),
        "active_care.decision": active_care.get("decision"),
        "active_care.auto_eat": active_care.get("auto_eat"),
        "active_care.priority_analysis": active_care.get("priority_analysis"),
        "journal": routing.get("journal_model"),
        "auto_heal.analysis": routing.get("auto_heal_models", {}).get("analysis"),
        "auto_heal.patch_generation": routing.get("auto_heal_models", {}).get("patch_generation"),
        "memory.distillation": routing.get("memory_models", {}).get("distillation"),
        "character_daily.plan_generator": routing.get("character_daily_models", {}).get("plan_generator"),
        "character_daily.sleep_decision": routing.get("character_daily_models", {}).get("sleep_decision"),
    }
    for route_name, model_path in routed_models.items():
        if model_path != official_m3:
            _fail(f"{route_name} 未直接使用 MiniMax 官方 M3: {model_path!r}")

    registered = PROVIDER_DEFAULT_MODELS.get("openrouter", [])
    if "openrouter/free" not in registered:
        _fail("OpenRouter 默认模型列表未注册 openrouter/free")
    concrete_free = [model for model in registered if str(model).endswith(":free")]
    if concrete_free:
        _fail(f"OpenRouter 默认模型列表仍有具体免费型号: {concrete_free}")

    # 4. cloud_router 判定与降级链路
    from core.llm.cloud_router import CloudRouterLLMModule

    obj = object.__new__(CloudRouterLLMModule)  # 绕过 __init__ 构造
    cases = [
        (free, True),
        (legacy_free_m3, True),
        ("cloud:openrouter:minimax/minimax-m2.7:free", True),
        (official_m3, False),
        ("cloud:deepseek:deepseek-v4-flash", False),
        ("cloud:openrouter:google/gemini-3.8-flash", False),
    ]
    for mp, expect in cases:
        got = obj._is_openrouter_free_model(mp)
        if got is not expect:
            _fail(f"_is_openrouter_free_model({mp!r}) 期望 {expect}，实际 {got}")

    reasoning_only = {
        "response": "",
        "reasoning_only": True,
        "reasoning_text": "内部推理不得进入用户消息",
    }
    if not obj._is_failed_chat_result(reasoning_only):
        _fail("reasoning_only 响应未被统一路由识别为失败")

    # 5. 免费聚合路由失败时走 MiniMax 官方 M3
    captured = {}

    def _fake_select(mp, kwargs):
        captured["mp"] = mp
        return "FAKE_CLIENT", dict(kwargs)

    obj._select_client = _fake_select
    active_fb = obj._pick_openrouter_free_fallback(
        free, {"temperature": 0.3, "max_new_tokens": 80}
    )
    if not active_fb:
        _fail("OpenRouter 免费聚合路由未取到 MiniMax 官方 M3 回退客户端")
    elif captured.get("mp") != official_m3:
        _fail(f"免费路由应回退到 {official_m3!r}，实际 {captured.get('mp')!r}")
    else:
        _, active_kwargs = active_fb
        if active_kwargs.get("temperature") != 0.3:
            _fail("Active Care 回退未保留原生成参数")

    # 6. 旧具体免费型号也兼容同一官方 M3 回退
    fb = obj._pick_openrouter_free_fallback(legacy_free_m3)
    if not fb:
        _fail("旧具体免费型号未取到 MiniMax 官方 M3 兜底客户端")
    else:
        fb_client, fb_kwargs = fb
        if fb_client != "FAKE_CLIENT":
            _fail("免费 minimax 兜底未选中桩客户端")
        if captured.get("mp") != official_m3:
            _fail(f"兜底应选择 {official_m3!r}，实际选择 {captured.get('mp')!r}")

    # 6. 非免费、非 Active Care 路径不越界（不应触发旧免费模型兜底）
    none_fb = obj._pick_openrouter_free_fallback("cloud:deepseek:deepseek-v4-flash")
    if none_fb is not None:
        _fail("非免费模型不应触发兜底")

    if failures:
        _out(f"汇总: {failures} 项检查失败")
        return 1
    _out("汇总: 后台任务已直接使用 MiniMax 官方 M3，免费模型仅保留手动兜底")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(check())
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.exit(1)
