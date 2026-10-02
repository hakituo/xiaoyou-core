#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证脚本: 模型自造的渠道标注（「（来自QQ）」「来自App」）会被剥离

背景：「（来自X）」是系统给跨渠道历史消息加的后缀。模型会照着历史格式自己
复述一个出来，用户看到「晚安（来自App）」这种莫名其妙的尾巴。

验证项：
1. core.utils.data.chat_channel.strip_model_channel_marks 覆盖全角/半角/句中/句尾裸写
2. 正常正文不被误伤（动作描写括号、来自QQ音乐、句中裸写）
3. 流式后处理链 postprocess_response 会剥
4. 非流式 handler_postprocess 会剥
5. 主动消息 pipeline 里有 ChannelMarkStripStep，且排在空检之前
6. QQ adapter 的清洗链复用了该函数（与时间戳剥离同一处）
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils.data.chat_channel import strip_model_channel_marks  # noqa: E402

QQ_MESSAGE_PATH = ROOT / "clients" / "bots" / "qq" / "session" / "message.py"


def check_strip_variants() -> list[str]:
    """场景1: 四种形态都要剥干净。"""
    issues = []
    cases = {
        "晚安（来自QQ）": "晚安",
        "晚安(来自App)": "晚安",
        "晚安（来自 手机）": "晚安",
        "（来自QQ）晚安": "晚安",
        "嗯，然后（来自App）晚安": "嗯，然后晚安",
        "晚安，来自QQ": "晚安，",
        "晚安。来自App。": "晚安。",
    }
    for before, expected in cases.items():
        after = strip_model_channel_marks(before)
        if after != expected:
            issues.append(f"[剥离] '{before}' 期望 '{expected}'，实际 '{after}'")
    return issues


def check_no_false_positive() -> list[str]:
    """场景2: 正常正文不能被误伤。"""
    issues = []
    keep_cases = [
        "晚安",
        "（轻轻揉了揉眼睛）困了",
        "这首歌来自QQ音乐",
        "这条消息来自App",
        "你那边应该睡得正沉，不打扰了",
    ]
    for text in keep_cases:
        after = strip_model_channel_marks(text)
        if after != text:
            issues.append(f"[误伤] '{text}' 被改成 '{after}'")
    return issues


def check_stream_postprocess() -> list[str]:
    """场景3: 流式后处理链接入了剥离。"""
    issues = []
    try:
        from core.agents.chat_agent_components.streaming_pipeline.postprocess import (
            postprocess_response,
            strip_channel_marks,
        )
    except Exception as exc:
        issues.append(f"[流式链] 导入失败: {exc}")
        return issues

    if strip_channel_marks("晚安（来自QQ）") != "晚安":
        issues.append("[流式链] strip_channel_marks 未剥离")
    full = postprocess_response("刚忙完（来自QQ）", [])
    if "来自" in full:
        issues.append(f"[流式链] postprocess_response 未剥离渠道标注: '{full}'")
    return issues


def check_nonstream_postprocess() -> list[str]:
    """场景4: 非流式 handler 后处理也剥。"""
    issues = []
    try:
        from core.agents.chat_agent_components.handler_postprocess import (
            _postprocess_response,
        )
    except Exception as exc:
        issues.append(f"[非流式链] 导入失败: {exc}")
        return issues

    result = _postprocess_response("刚忙完（来自App）", [], False)
    if "来自" in result.final_content:
        issues.append(f"[非流式链] final_content 仍含渠道标注: '{result.final_content}'")
    if "来自" in result.full_content:
        issues.append(f"[非流式链] full_content 仍含渠道标注: '{result.full_content}'")
    return issues


def check_active_care_pipeline() -> list[str]:
    """场景5: 主动消息 pipeline 的 step 存在且顺序正确。"""
    issues = []
    try:
        from core.services.active_care.postprocess.pipeline import (
            ChannelMarkStripStep,
            DEFAULT_STEPS,
        )
    except Exception as exc:
        issues.append(f"[主动消息] 导入失败: {exc}")
        return issues

    names = [step.name for step in DEFAULT_STEPS if hasattr(step, "name")]
    if "channel_mark_strip" not in names:
        issues.append("[主动消息] DEFAULT_STEPS 缺少 channel_mark_strip")
        return issues
    idx_mark = names.index("channel_mark_strip")
    idx_empty = names.index("empty_after_strip_check")
    if idx_mark > idx_empty:
        issues.append("[主动消息] channel_mark_strip 必须在空检之前")

    # 直接跑一次 step：整条只剩标注时剥完应为空
    class _State:
        def __init__(self, text):
            self.final_text = text
            self.full_raw_text = text
            self.message_type = "text"
            self.llm_thought = None

    state = _State("（来自QQ）")
    asyncio.run(ChannelMarkStripStep().run(state, None, None))
    if state.final_text.strip():
        issues.append(f"[主动消息] 只剩标注时应剥为空，实际 '{state.final_text}'")

    state2 = _State("困了，先睡了（来自App）")
    asyncio.run(ChannelMarkStripStep().run(state2, None, None))
    if state2.final_text != "困了，先睡了":
        issues.append(f"[主动消息] 剥离结果异常: '{state2.final_text}'")
    if "来自" in state2.full_raw_text:
        issues.append(f"[主动消息] full_raw_text 未同步剥离: '{state2.full_raw_text}'")
    return issues


def check_qq_adapter_reuses_it() -> list[str]:
    """场景6: QQ adapter 的清洗链复用 core 实现（与时间戳剥离同一处）。"""
    issues = []
    try:
        from clients.bots.qq.utils import strip_model_channel_marks as qq_strip
    except Exception as exc:
        issues.append(f"[QQ adapter] utils 未导出 strip_model_channel_marks: {exc}")
        return issues

    if qq_strip is not strip_model_channel_marks:
        issues.append("[QQ adapter] 复用的不是 core 的实现")

    source = QQ_MESSAGE_PATH.read_text(encoding="utf-8")
    marker = "strip_model_channel_marks(full_response)"
    if marker not in source:
        issues.append(f"[QQ adapter] message.py 未调用 {marker}")
    # 必须紧跟在时间戳剥离之后，两处清洗保持同一处复用
    ts_idx = source.find("strip_ai_timestamp(full_response)")
    ch_idx = source.find(marker)
    if ts_idx < 0 or ch_idx < ts_idx:
        issues.append("[QQ adapter] 渠道剥离未排在时间戳剥离之后")
    return issues


def main() -> int:
    checks = [
        ("四种形态都被剥离", check_strip_variants),
        ("正常正文不误伤", check_no_false_positive),
        ("流式后处理链", check_stream_postprocess),
        ("非流式后处理链", check_nonstream_postprocess),
        ("主动消息 pipeline", check_active_care_pipeline),
        ("QQ adapter 复用", check_qq_adapter_reuses_it),
    ]

    all_issues = []
    for name, check in checks:
        try:
            issues = check()
        except Exception as exc:
            issues = [f"执行异常: {exc}"]
        print(f"[{'PASS' if not issues else 'FAIL'}] {name}")
        for issue in issues:
            print(f"    - {issue}")
        all_issues.extend(issues)

    if all_issues:
        print(f"\n验证失败，共 {len(all_issues)} 项问题")
        return 1
    print("\n全部通过：模型自造的渠道标注在四条输出链路上都会被剥离")
    return 0


if __name__ == "__main__":
    sys.exit(main())
