#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 Active Care 直接使用 MiniMax 官方 M3

检查点：
1. active_care_models 全部指向 cloud:minimax:MiniMax-M3
2. 不再配置 Active Care 二次回退
3. 配置访问层能识别全部 Active Care 主模型

用法：
    venv_core\\python.exe tests\\scripts\\llm\\verify_active_care_model_config.py

退出码：0=通过；非0=任一检查失败。
说明：诊断统一输出到 stderr，规避部分核心模块对 stdout 的重定向。
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)


def _out(msg: str):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def check() -> int:
    failures = 0

    def _fail(msg: str):
        nonlocal failures
        failures += 1
        _out(msg)

    # 1. 读取 model_routing.yaml，定位 active_care_models 区段
    yaml_text = Path(ROOT, "config", "yaml", "sections", "model_routing.yaml").read_text(
        encoding="utf-8"
    )
    start = yaml_text.find("active_care_models:")
    end = yaml_text.find("journal_model:", start)
    block = yaml_text[start:end] if start >= 0 else ""

    # 2. 主链不得再引用任何 OpenRouter 免费端点
    for bad in ["openrouter/free", "minimax/minimax-m3:free", "minimax/minimax-m2.7:free"]:
        if bad in block:
            _fail(f"active_care_models 仍引用具体免费端点 '{bad}'")

    official_m3 = "cloud:minimax:MiniMax-M3"
    field_expect = {
        "default:": official_m3,
        "ling:": official_m3,
        "decision:": official_m3,
        "auto_eat:": official_m3,
        "priority_analysis:": official_m3,
    }
    for field in field_expect:
        line = next((ln for ln in block.splitlines() if ln.strip().startswith(field)), None)
        if line is None:
            _fail(f"yaml 缺少字段 {field}")
            continue
        if field_expect[field] not in line:
            _fail(f"{field} 未直接使用 MiniMax 官方 M3，当前: {line.strip()}")

    # 3. 配置访问层应返回主链与免费聚合回退
    sys.path.insert(0, str(ROOT))
    from config.model_config import (
        get_active_care_primary_models,
        get_fallback_model_for_active_care,
    )

    if get_active_care_primary_models() != {official_m3}:
        _fail(
            "Active Care 主模型集合异常: "
            f"{sorted(get_active_care_primary_models())}"
        )
    if get_fallback_model_for_active_care() != "":
        _fail(
            "Active Care fallback 异常: "
            f"{get_fallback_model_for_active_care()!r}"
        )

    # 4. 备用官方 M3 仍按原生多模态模型识别
    from core.llm.model_capabilities import is_vision_model

    vision = is_vision_model(official_m3)
    _out(f"[OK] Active Care 主链 = {official_m3}")
    _out("[OK] Active Care fallback = 空（不重复调用同一模型）")
    _out(f"[OK] minimax-m3 is_vision_model = {vision}（True 表示 M3 自带视觉，发图走一阶段直通）")

    if failures:
        _out(f"汇总: {failures} 项检查失败")
        return 1
    _out("汇总: Active Care 已直接使用 MiniMax 官方 M3")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(check())
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.exit(1)
