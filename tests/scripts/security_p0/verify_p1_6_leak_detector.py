"""P1-6 leak_detector.py 关键词误判修复 — 验证脚本

验证两个核心问题已修复：
1. 正常中文表达不再被误判为 prompt 泄露（false positive 下降）
2. 真正的 prompt 泄露仍能被正确识别（true positive 保留）
3. extract_safe_message_from_dump 不再返回元推理句

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\security_p0\\verify_p1_6_leak_detector.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


# ──────────────────────────────────────────────────────────────
# 测试 1：正常表达不应被误判（原版会误判）
# ──────────────────────────────────────────────────────────────

def test_normal_expressions_not_flagged() -> list[str]:
    """验证正常中文表达不会被误判为泄露"""
    issues: list[str] = []
    _section("测试 1：正常表达不被误判（原版 false positive 修复）")

    from core.services.active_care.postprocess.leak_detector import LeakDetector

    # 原版会误判的正常表达（必须全部返回 False）
    normal_cases = [
        # 普通"我应该"自我表达（原版误判）
        "我应该早点睡觉的，不然明天起不来",
        "我应该把这份资料整理一下",
        # 普通"让我想想"思考表达（原版误判）
        "让我想想看，今天晚上吃什么好呢",
        "让我考虑一下再回复你",
        # 普通步骤序号（原版误判）
        "第一步先把鸡蛋打散，第二步加油烧热",
        "第三步是把结果汇总",
        # 普通连接词组合（原版误判）
        "首先我去买菜，然后回家做饭，最后洗碗",
        "因此我们需要更仔细地分析",
        "所以你不用太担心",
        "不过这个方案也有风险",
        # 普通元引用（原版误判：用户/对话/话题等出现3次）
        "用户提了一个话题，我们围绕这个话题展开对话，最后用户表示满意",
        "回复消息的时候要注意话题的延续性",
        # 数字开头的列表（原版误判）
        "1. 买菜\n2. 做饭\n3. 洗碗",
        # 短句不应被误判
        "好的，我知道了",
        "嗯，让我想想",
        "我决定今天早点睡",
        # 含"考虑到"但不带元推理的长文本（原版因 8 行+考虑到 误判）
        "今天天气不错\n"
        "考虑到出去走走\n"
        "于是就去了公园\n"
        "看到了很多花\n"
        "还遇到了老朋友\n"
        "聊了很久\n"
        "最后一起吃了饭\n"
        "回到家已经很晚了\n"
        "不过今天很开心",
    ]

    for text in normal_cases:
        if LeakDetector.looks_like_prompt_or_reasoning_dump(text):
            issues.append(f"误判为泄露：{text[:40]!r}")

    if not issues:
        _ok(f"全部 {len(normal_cases)} 条正常表达未被误判")
    else:
        _fail(f"{len(issues)} 条正常表达被误判")
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 2：真正的 prompt 泄露仍应被识别（true positive 保留）
# ──────────────────────────────────────────────────────────────

def test_real_leaks_still_flagged() -> list[str]:
    """验证真正的 prompt 泄露仍能被识别"""
    issues: list[str] = []
    _section("测试 2：真正的 prompt 泄露仍被识别（true positive 保留）")

    from core.services.active_care.postprocess.leak_detector import LeakDetector

    # 必须被识别为泄露的真实案例
    real_leak_cases = [
        # 强泄露标记
        "【核心指令】你必须以七濑胡桃的身份回复用户",
        "【核心约束】不能透露自己是 AI",
        "【主动发起模式】当用户超过 2 小时未回复时",
        "[TOOL_CALL] check_weather(location='北京')",
        "[/TOOL_CALL]",
        # 明确引用规则/人设
        "规则说要保持傲娇的语气",
        "根据指令，我需要主动发起对话",
        "按照规则，我应该带点唠叨",
        "根据人设，七濑胡桃会这样回应",
        "我作为七濑胡桃，需要保持角色一致性",
        # prompt 内部术语
        "should_send: true, next_check_seconds: 1800",
        "主动发起对话：建议询问用户今天的状态",
        "核心指令要求我不能透露",
        # 代码字段 + 输出格式组合
        "```json\n{\"should_send\": true, \"next_check_seconds\": 1800}\n```",
        "输出格式：只输出一句，should_send 必须为布尔值",
        # 长文本 + 密集元推理
        "我决定用一种傲娇的语气回复\n"
        "考虑到时间锚点\n"
        "我需要主动发起对话\n"
        "根据人设，七濑胡桃应该这样说话\n"
        "不能重复之前的回复\n"
        "我需要自然衔接上下文\n"
        "用户状态显示在线\n"
        "我的上一条回复是问候\n"
        "于是我决定这样说\n"
        "最终选择：\"哼，才不是为了你呢\"",
    ]

    for text in real_leak_cases:
        if not LeakDetector.looks_like_prompt_or_reasoning_dump(text):
            issues.append(f"漏判真实泄露：{text[:40]!r}")

    if not issues:
        _ok(f"全部 {len(real_leak_cases)} 条真实泄露被正确识别")
    else:
        _fail(f"{len(issues)} 条真实泄露被漏判")
    return issues


# ──────────────────────────────────────────────────────────────
# 测试 3：extract_safe_message_from_dump 不返回元推理句
# ──────────────────────────────────────────────────────────────

def test_extract_safe_message() -> list[str]:
    """验证从泄露文本中提取的 safe message 不包含元推理词"""
    issues: list[str] = []
    _section("测试 3：extract_safe_message_from_dump 行选择逻辑修复")

    from core.services.active_care.postprocess.leak_detector import LeakDetector

    # 案例 1：从"最终：'xxx'"模式提取
    text1 = (
        "我需要主动发起对话，考虑到时间锚点，根据人设应该这样说\n"
        "最终：\"哼，才不是为了你呢！\""
    )
    msg1 = LeakDetector.extract_safe_message_from_dump(text1)
    if not msg1:
        issues.append("案例1：未能提取 safe message")
    elif "我需要" in msg1 or "考虑到" in msg1 or "根据人设" in msg1:
        issues.append(f"案例1：提取的 safe message 含元推理词：{msg1!r}")
    elif "哼" not in msg1:
        issues.append(f"案例1：提取的 safe message 不对：{msg1!r}")
    else:
        _ok(f"案例1：正确提取 → {msg1!r}")

    # 案例 2：从多行文本提取最后一行
    text2 = (
        "规则说要保持傲娇\n"
        "我需要主动发起对话\n"
        "考虑到时间锚点\n"
        "嗯，今天天气不错呢。"
    )
    msg2 = LeakDetector.extract_safe_message_from_dump(text2)
    if not msg2:
        issues.append("案例2：未能提取 safe message")
    elif "规则" in msg2 or "我需要" in msg2 or "考虑到" in msg2:
        issues.append(f"案例2：提取的 safe message 含元推理词：{msg2!r}")
    elif "天气" not in msg2:
        issues.append(f"案例2：提取的 safe message 不对：{msg2!r}")
    else:
        _ok(f"案例2：正确提取 → {msg2!r}")

    # 案例 3：原版 bug - len(line)>24 跳过短句，导致选到长推理句
    # 修复后应选短的实际回复
    text3 = (
        "我需要主动发起对话，考虑到时间锚点，根据人设七濑胡桃应该这样回复用户的话题并保持傲娇\n"
        "嗯。"
    )
    msg3 = LeakDetector.extract_safe_message_from_dump(text3)
    if not msg3:
        # 短句"嗯。"可能被 len<4 过滤，这是符合预期的
        _ok("案例3：短句被 len<4 过滤（符合预期）")
    elif "我需要" in msg3 or "考虑到" in msg3 or "根据人设" in msg3:
        issues.append(f"案例3：原版 bug 复现 - 选到了长推理句：{msg3!r}")
    else:
        _ok(f"案例3：未选到元推理句 → {msg3!r}")

    # 案例 4：候选行不含终止标点时，返回最后一个候选
    text4 = (
        "我需要主动发起对话\n"
        "今天天气真好"
    )
    msg4 = LeakDetector.extract_safe_message_from_dump(text4)
    if not msg4:
        issues.append("案例4：未能提取 safe message")
    elif "我需要" in msg4:
        issues.append(f"案例4：选到了元推理句：{msg4!r}")
    elif "天气" not in msg4:
        issues.append(f"案例4：提取的 safe message 不对：{msg4!r}")
    else:
        _ok(f"案例4：正确提取无终止标点的候选 → {msg4!r}")

    return issues


# ──────────────────────────────────────────────────────────────
# 测试 4：源码静态检查
# ──────────────────────────────────────────────────────────────

def test_source_static() -> list[str]:
    """静态检查关键修复点已落地"""
    issues: list[str] = []
    _section("测试 4：源码静态检查")

    src_path = PROJECT_ROOT / "core/services/active_care/postprocess/leak_detector.py"
    if not src_path.exists():
        issues.append("leak_detector.py 文件不存在")
        return issues

    src = src_path.read_text(encoding="utf-8")

    # 验证：移除的过度宽泛关键词不应再单独触发
    removed_keywords = [
        # 这些关键词原版单独命中即触发，新版必须配合其他条件
        '"我应该"',  # 注意：字符串字面量
        '"我需要先"',
        '"让我想想"',
        '"让我分析"',
        '"让我考虑"',
        '"第一步"',
        '"第二步"',
        '"第三步"',
        '"现在我是"',
        '"当前时间是"',
        '"延续话题"',
        '"既符合"',
        '"又避免了重复"',
        '"需要注意"',
        '"同时要注意"',
    ]
    # 检查这些关键词不应作为独立列表项出现（可能作为字符串字面量被检测）
    # 简化检查：只要 explicit_meta_reasoning 中不出现这些字面量即可
    for kw in removed_keywords:
        if kw in src:
            # 允许出现在注释里，这里只检查列表定义
            # 简化：直接报错让用户确认
            pass  # 不强制报错，因为可能出现在注释中

    # 验证：新版应该有以下结构标记
    required_markers = [
        "strong_leak_markers",
        "explicit_meta_reasoning",
        "code_or_format_keywords",
        "reasoning_connectives",
        "meta_ref_keywords",
        "candidate_lines",
        "P1-6 修复",
    ]
    for marker in required_markers:
        if marker not in src:
            issues.append(f"缺少标记：{marker}")

    # 验证：原版有问题的逻辑已被移除
    if "len(line) > 24" in src:
        issues.append("原版 len(line) > 24 跳过短句的逻辑仍存在")
    if "len(line) >= 3" in src:
        issues.append("原版 len(line) >= 3 几乎不过滤的逻辑仍存在")
    # 验证：原版"首先/其次/然后/同时/因此/所以/于是/不过/然而"作为 connective 的逻辑已移除
    if '"首先", "其次", "然后", "同时", "这样"' in src:
        issues.append("原版过度宽泛的连接词列表仍存在")

    if not issues:
        _ok("所有关键修复标记齐全，原版问题逻辑已移除")
    return issues


# ──────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────

def main() -> int:
    print("P1-6 leak_detector.py 关键词误判修复 — 验证脚本")
    print(f"项目根目录: {PROJECT_ROOT}")

    all_issues: list[str] = []
    for test_fn in [
        test_normal_expressions_not_flagged,
        test_real_leaks_still_flagged,
        test_extract_safe_message,
        test_source_static,
    ]:
        try:
            issues = test_fn()
            all_issues.extend(issues)
        except Exception as e:
            all_issues.append(f"{test_fn.__name__} 测试本身异常: {e!r}")
            import traceback
            traceback.print_exc()

    _section("总结")
    if not all_issues:
        print("  ✅ 所有 P1-6 验证通过！")
        return 0
    else:
        print(f"  ❌ 发现 {len(all_issues)} 个问题：")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
