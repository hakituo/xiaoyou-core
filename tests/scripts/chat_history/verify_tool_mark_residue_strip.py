#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证脚本: 残留的工具调用标记（DSML token 及漂移形态）在四条输出链路上都会被剥离

背景：DeepSeek 系模型偶发把内部工具调用 token 当正文吐出来。2026-09-29 实测
泄漏形态是漂移过的 —— 容器丢了 ``tool_`` 前缀（``<｜｜｜DSML｜｜｜ calls>``）、
前缀与标签名之间多了空格、开闭标签空白不一致。旧解析器用原样字符串匹配，
认不出漂移形态，token 就原样流给了用户。

修复口径：
- 解析层容错（dsml_parser / dsml_stream / tag_stream_parser 共用一套容错正则）；
- 输出侧通用清洗 strip_tool_mark_residue 补齐到四条链路。

验证项：
1. strip_tool_mark_residue 覆盖完整漂移块 / 未闭合块 / 拆散残片 / 裸前缀
2. 正常正文不被误伤
3. 流式后处理链 postprocess_response 会剥
4. 非流式 handler_postprocess 会剥
5. 主动消息 pipeline 有 ToolMarkStripStep，且排在空检之前
6. QQ adapter 的清洗链复用了该函数（源码级 + 导入级）
7. LLM 客户端流式过滤用容错正则并带 flush 收尾
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm.openai_compat.dsml_parser import (  # noqa: E402
    strip_tool_mark_residue,
)

V4 = "\uff5c\uff5cDSML\uff5c\uff5c"
V3 = "\uff5cDSML\uff5c"
QQ_MESSAGE_PATH = ROOT / "clients" / "bots" / "qq" / "session" / "message.py"
QQ_TRANSPORT_PATH = ROOT / "clients" / "bots" / "qq" / "transport.py"
CLIENT_PATH = ROOT / "core" / "llm" / "openai_compat" / "client.py"
TAG_PARSER_PATH = (
    ROOT / "core" / "agents" / "chat_agent_components" / "streaming_pipeline"
    / "tag_stream_parser.py"
)


def _drift_block() -> str:
    """2026-09-29 实测漂移形态：calls 别名 + 前缀后多空格 + 开闭空白不一致。"""
    return (
        f"<{V4} calls>"
        f'<{V4} invoke name="search_chat_history">'
        f'<{V4} parameter name="query" string="true">念叨 唠叨</{V4} parameter>'
        f"</{V4} invoke>"
        f"</{V4} calls>"
    )


def check_strip_variants() -> list[str]:
    """场景1: 四种残留形态都要剥干净。"""
    issues = []
    cases = {
        "完整漂移块": (f"我先看看记录。{_drift_block()}", "我先看看记录。"),
        "未闭合块": (f"晚安。<{V4} calls><{V4} invoke name=\"s\"", "晚安。"),
        "拆散残片": (f"稍等</{V4}invoke>\n\n好的", "稍等\n\n好的"),
        "裸前缀": (f"马上<{V4}", "马上"),
        "V3 残片": (f"嗯</{V3}function_calls>", "嗯"),
    }
    for label, (before, expected) in cases.items():
        after = strip_tool_mark_residue(before)
        if after != expected:
            issues.append(f"[剥离/{label}] 期望 {expected!r}，实际 {after!r}")
        if "DSML" in after or "\uff5c" in after:
            issues.append(f"[剥离/{label}] 仍残留标记: {after!r}")
    return issues


def check_no_false_positive() -> list[str]:
    """场景2: 正常正文不能被误伤。"""
    issues = []
    keep_cases = [
        "晚安",
        "（轻轻揉了揉眼睛）困了",
        "这首歌来自QQ音乐",
        "用了 | 分隔",
        "3 < 5 是对的",
    ]
    for text in keep_cases:
        after = strip_tool_mark_residue(text)
        if after != text:
            issues.append(f"[误伤] {text!r} 被改成 {after!r}")
    return issues


def check_stream_postprocess() -> list[str]:
    """场景3: 流式后处理链接入了剥离。"""
    issues = []
    try:
        from core.agents.chat_agent_components.streaming_pipeline.postprocess import (
            postprocess_response,
        )
    except Exception as exc:
        issues.append(f"[流式链] 导入失败: {exc}")
        return issues

    full = postprocess_response(f"刚忙完{_drift_block()}", [])
    if "DSML" in full or "\uff5c" in full:
        issues.append(f"[流式链] postprocess_response 未剥离: {full!r}")
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

    result = _postprocess_response(f"刚忙完{_drift_block()}", [], False)
    for field in ("final_content", "full_content"):
        value = getattr(result, field, "")
        if "DSML" in value or "\uff5c" in value:
            issues.append(f"[非流式链] {field} 仍含工具标记: {value!r}")
    return issues


def check_active_care_pipeline() -> list[str]:
    """场景5: 主动消息 pipeline 的 step 存在且顺序正确。"""
    issues = []
    try:
        from core.services.active_care.postprocess.pipeline import (
            ToolMarkStripStep,
            DEFAULT_STEPS,
        )
    except Exception as exc:
        issues.append(f"[主动消息] 导入失败: {exc}")
        return issues

    names = [step.name for step in DEFAULT_STEPS if hasattr(step, "name")]
    if "tool_mark_strip" not in names:
        issues.append("[主动消息] DEFAULT_STEPS 缺少 tool_mark_strip")
        return issues
    if names.index("tool_mark_strip") > names.index("empty_after_strip_check"):
        issues.append("[主动消息] tool_mark_strip 必须在空检之前")

    class _State:
        def __init__(self, text):
            self.final_text = text
            self.full_raw_text = text
            self.message_type = "text"
            self.llm_thought = None

    state = _State(_drift_block())
    asyncio.run(ToolMarkStripStep().run(state, None, None))
    if state.final_text.strip():
        issues.append(f"[主动消息] 只剩标记时应剥为空，实际 {state.final_text!r}")

    state2 = _State(f"困了，先睡了{_drift_block()}")
    asyncio.run(ToolMarkStripStep().run(state2, None, None))
    if state2.final_text != "困了，先睡了":
        issues.append(f"[主动消息] 剥离结果异常: {state2.final_text!r}")
    if "DSML" in state2.full_raw_text or "\uff5c" in state2.full_raw_text:
        issues.append(f"[主动消息] full_raw_text 未同步剥离: {state2.full_raw_text!r}")
    return issues


def check_qq_adapter_reuses_it() -> list[str]:
    """场景6: QQ adapter 清洗链复用 core 实现（导入级 + 源码级）。"""
    issues = []
    try:
        from clients.bots.qq.utils import strip_tool_mark_residue as qq_strip
    except Exception as exc:
        issues.append(f"[QQ adapter] utils 未导出 strip_tool_mark_residue: {exc}")
        return issues

    if qq_strip is not strip_tool_mark_residue:
        issues.append("[QQ adapter] 复用的不是 core 的实现")

    for path, marker in (
        (QQ_MESSAGE_PATH, "strip_tool_mark_residue(full_response)"),
        (QQ_TRANSPORT_PATH, "strip_tool_mark_residue(content)"),
    ):
        source = path.read_text(encoding="utf-8")
        if marker not in source:
            issues.append(f"[QQ adapter] {path.name} 未调用 {marker}")
    return issues


def check_stream_filter_tolerance() -> list[str]:
    """场景7: LLM 客户端流式过滤用容错正则 + flush 收尾。"""
    issues = []
    client_src = CLIENT_PATH.read_text(encoding="utf-8")
    if "dsml_filter.flush()" not in client_src:
        issues.append("[流式过滤] client.py 缺少 dsml_filter.flush() 收尾")

    tag_src = TAG_PARSER_PATH.read_text(encoding="utf-8")
    if "DSML_START_RE = _DSML_START_RE" not in tag_src:
        issues.append("[流式过滤] tag_stream_parser 未复用容错正则")

    try:
        from core.llm.openai_compat.dsml_stream import DSMLStreamFilter
    except Exception as exc:
        issues.append(f"[流式过滤] 导入失败: {exc}")
        return issues

    # 漂移开标签被拆成两个 chunk，过滤器必须扣留而不是透传
    f = DSMLStreamFilter()
    out1 = f.filter_chunk({"content": f"你好<{V4} cal"})
    out2 = f.filter_chunk({"content": "ls>" + _drift_block()[len(f"<{V4} calls>"):]})
    leaked = "".join(c.get("content", "") for c in out1 + out2)
    if "DSML" in leaked or "\uff5c" in leaked:
        issues.append(f"[流式过滤] 漂移 token 泄漏到可见文本: {leaked!r}")
    if not any("tool_calls" in c for c in out1 + out2):
        issues.append("[流式过滤] 漂移块未被解析成 tool_calls")
    return issues


def main() -> int:
    checks = [
        ("四种残留形态都被剥离", check_strip_variants),
        ("正常正文不误伤", check_no_false_positive),
        ("流式后处理链", check_stream_postprocess),
        ("非流式后处理链", check_nonstream_postprocess),
        ("主动消息 pipeline", check_active_care_pipeline),
        ("QQ adapter 复用", check_qq_adapter_reuses_it),
        ("流式过滤容错 + 收尾", check_stream_filter_tolerance),
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
    print("\n全部通过：残留的工具调用标记在四条输出链路上都会被剥离")
    return 0


if __name__ == "__main__":
    sys.exit(main())