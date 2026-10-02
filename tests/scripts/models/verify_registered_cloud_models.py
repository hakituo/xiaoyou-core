#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证模型选择界面的注册池范围与排序。

背景：
    往 PROVIDER_DEFAULT_MODELS 里注册模型，只表示"这个 provider 认识这个型号"，
    并不等于它会出现在换模型界面。界面列表由 ModelManager 的注册池决定，中间还有
    两道闸：registered_cloud_providers（provider 级白名单）与 registered_cloud_models
    （型号级白名单）。曾出现过"注册成功但 UI 看不到"的情况，本脚本把这条链路钉住。

检查项：
    1. siliconflow 已进入 provider 白名单
    2. 型号级白名单把 siliconflow 收敛到 deepseek-ai/DeepSeek-V3.2（不放整个注册池）
    3. 按 ModelManager 的同款过滤逻辑推演，siliconflow 最终进池的型号只有 V3.2
    4. 列表排序按展示名首字母（忽略大小写）

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\models\\verify_registered_cloud_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

EXPECTED_SILICONFLOW_MODELS = ["deepseek-ai/DeepSeek-V3.2"]


def check_provider_whitelist(settings) -> bool:
    providers = [str(p).strip().lower() for p in (settings.model.registered_cloud_providers or [])]
    ok = "siliconflow" in providers
    print(f"  [{'OK' if ok else 'FAIL'}] provider 白名单含 siliconflow: {providers}")
    return ok


def check_model_whitelist(settings) -> bool:
    raw = getattr(settings.model, "registered_cloud_models", None) or {}
    picked = [str(m).strip() for m in (raw.get("siliconflow") or [])]
    ok = picked == EXPECTED_SILICONFLOW_MODELS
    print(f"  [{'OK' if ok else 'FAIL'}] siliconflow 型号白名单: {picked}（期望 {EXPECTED_SILICONFLOW_MODELS}）")
    return ok


def check_queue_result(settings) -> bool:
    """按 model_manager 的同款规则推演进池型号。"""
    from config.settings_model import PROVIDER_DEFAULT_MODELS

    allowed_providers = {str(p).strip().lower() for p in (settings.model.registered_cloud_providers or [])}
    raw_models = getattr(settings.model, "registered_cloud_models", None) or {}
    allowed_models = {
        str(p).strip().lower(): {str(m).strip() for m in (models or [])}
        for p, models in raw_models.items()
    }

    pooled: dict[str, list[str]] = {}
    for provider, models in PROVIDER_DEFAULT_MODELS.items():
        norm = str(provider).strip().lower()
        if allowed_providers is not None and norm not in allowed_providers:
            continue
        allowed = allowed_models.get(norm)
        pooled[norm] = [
            m for m in models if allowed is None or str(m).strip() in allowed
        ]

    sf = pooled.get("siliconflow", [])
    ok = sf == EXPECTED_SILICONFLOW_MODELS
    print(f"  [{'OK' if ok else 'FAIL'}] 推演进池的 siliconflow 型号: {sf}（期望 {EXPECTED_SILICONFLOW_MODELS}）")
    print("        其它 provider 进池: " + ", ".join(
        f"{p}={v}" for p, v in sorted(pooled.items()) if p != "siliconflow"
    ))
    return ok


def check_sorting() -> bool:
    """排序键与 routers/v1/models.py 保持一致：按展示名忽略大小写升序。"""
    samples = [
        {"name": "qwen3-max", "id": "qwen3-max"},
        {"name": "DeepSeek-V3.2", "id": "DeepSeek-V3.2"},
        {"name": "anthropic/claude-opus-4.6", "id": "anthropic/claude-opus-4.6"},
        {"name": "MiniMax-M3", "id": "MiniMax-M3"},
    ]
    sorted_names = [
        str(m.get("name") or m.get("id") or "")
        for m in sorted(samples, key=lambda m: str(m.get("name") or m.get("id") or "").lower())
    ]
    expected = ["anthropic/claude-opus-4.6", "DeepSeek-V3.2", "MiniMax-M3", "qwen3-max"]
    ok = sorted_names == expected
    print(f"  [{'OK' if ok else 'FAIL'}] 首字母排序: {sorted_names}")
    return ok


def main() -> int:
    print("=" * 70)
    print("模型选择界面注册池验证")
    print("=" * 70)

    from config.integrated_config import get_settings

    settings = get_settings()
    results = [
        check_provider_whitelist(settings),
        check_model_whitelist(settings),
        check_queue_result(settings),
        check_sorting(),
    ]

    print("=" * 70)
    if all(results):
        print("✅ 全部通过：siliconflow 只放行 V3.2，列表按首字母排序")
        return 0
    print(f"❌ 有 {results.count(False)} 项未通过")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
