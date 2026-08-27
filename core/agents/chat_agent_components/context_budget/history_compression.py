# -*- coding: utf-8 -*-
"""历史消息压缩（纯函数模块）。

职责：对历史消息列表做压缩，包括长消息摘要和学习会话压缩。
不依赖 memory_manager、不依赖外部 IO，纯 List[Dict] → List[Dict]。

被 history_fetch.py 调用，外部不直接使用。
"""

import re
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from ._utils import safe_int

logger = get_logger("ChatAgent")


def _extract_sentence_summary(text: str, max_chars: int = 160) -> str:
    """从长文本中提取首句+关键词摘要，用于上下文压缩"""
    s = str(text or "").strip()
    if not s:
        return ""
    # 取第一个完整句子（到第一个句末标点）
    m = re.match(r"^.{8,}?(?:[。！？!?\n])", s, re.DOTALL)
    if m:
        first_sentence = m.group(0).strip()
    else:
        first_sentence = s[:min(80, len(s))].strip()
    if len(first_sentence) > max_chars:
        first_sentence = first_sentence[:max_chars - 3].rstrip() + "..."
    return first_sentence


def condense_long_messages_in_history(
    history: List[Dict[str, Any]],
    recent_window: int = 6,
    threshold_chars: int = 400,
    max_summary_chars: int = 160,
) -> List[Dict[str, Any]]:
    """对非近期窗口的长 assistant 消息进行摘要压缩，节省上下文 token

    【设计原则】
    - 仅压缩 assistant 角色的消息（用户消息保持原样）
    - 最近 recent_window 条消息不做任何修改（保持近期对话原貌）
    - 只在上下文构建管线中生效，不修改短期记忆原文
    - 搜索工具和 RAG 检索不受影响（它们读 STM 原文）

    Args:
        history: 经过 sanitize 处理的历史消息列表
        recent_window: 最近保留原貌的消息数量
        threshold_chars: assistant 消息超过该字符数时触发压缩
        max_summary_chars: 压缩后摘要的最大字符数

    Returns:
        压缩后的历史消息列表（新列表，不影响原列表）
    """
    if not history:
        return history

    n = len(history)
    if n <= recent_window:
        return history

    result: List[Dict[str, Any]] = []
    compressed_count = 0
    saved_chars = 0

    for i, msg in enumerate(history):
        role = str(msg.get("role") or "").strip()
        content = str(msg.get("content") or "").strip()
        content_len = len(content)

        # 只压缩非近期窗口的 assistant 长消息
        if (
            i < n - recent_window
            and role == "assistant"
            and content_len > threshold_chars
        ):
            # 生成摘要
            summary = _extract_sentence_summary(content, max_summary_chars)
            if summary:
                original_chars = content_len
                condensed_content = (
                    f"[上下文压缩] 之前详细回复（约{original_chars}字）：{summary}"
                )
                entry = dict(msg)
                entry["content"] = condensed_content
                result.append(entry)
                compressed_count += 1
                saved_chars += original_chars - len(condensed_content)
                continue

        result.append(msg)

    if compressed_count > 0:
        logger.info(
            "上下文长消息压缩：压缩 %d 条旧 assistant 消息，"
            "节省约 %d 字符（recent_window=%d, threshold=%d）",
            compressed_count, saved_chars, recent_window, threshold_chars,
        )

    return result


# ============================================================
# 学习会话检测与压缩
# ============================================================

# 扩展的学习内容关键词（覆盖更宽泛的知识性对话）
_STUDY_CONTENT_KEYWORDS = [
    # 语言学
    "音译", "梵文", "梵语", "语系", "方言", "语法", "词汇", "词源", "构词",
    "印欧语系", "汉藏语系", "达罗毗荼语系", "泰米尔语", "印地语",
    "语言", "文字", "巴利语", "藏语", "汉语", "英语", "日语", "韩语",
    "法语", "德语", "西班牙语", "阿拉伯语", "波斯语",
    # 历史
    "殖民", "独立", "分治", "王朝", "帝国", "条约", "赔款", "战争",
    "抗战", "二战", "一战", "革命", "改革", "宪法", "历史",
    "古印度", "莫卧儿", "孔雀王朝", "笈多王朝", "德里苏丹国",
    "阿育王", "释迦牟尼", "佛陀", "雅利安", "达罗毗荼",
    "波斯", "希腊", "罗马", "蒙古", "突厥", "阿拉伯",
    # 地理
    "地形", "高原", "平原", "山脉", "河流", "气候", "洋流", "地貌",
    "地理", "印度", "中国", "美国", "英国", "日本",
    "恒河", "喜马拉雅", "德干高原", "泰姬陵",
    "德里", "新加坡", "巴基斯坦", "孟加拉", "斯里兰卡", "尼泊尔",
    "西藏", "新疆", "蒙古", "西伯利亚", "中东", "东南亚", "南亚", "东亚",
    # 宗教/哲学
    "佛经", "般若", "金刚经", "心经", "圣经", "古兰经", "宗教", "哲学",
    "佛教", "印度教", "伊斯兰教", "锡克教", "耆那教", "基督教", "犹太教",
    "菩萨", "罗汉", "涅槃", "轮回", "因果", "禅宗", "净土", "密宗",
    "小乘", "大乘", "南传", "北传", "藏传",
    "道教", "儒教", "孔孟", "老庄", "易经", "道德经",
    # 社会科学
    "经济", "政治", "社会", "文化", "民族", "种族",
    "人类学", "社会学", "心理学", "教育学", "传播学",
    "法律", "宪法", "刑法", "民法", "国际法",
    # 自然科学
    "物理", "化学", "生物", "数学", "天文", "地质",
    "量子", "相对论", "进化论", "基因", "DNA", "RNA",
    "细胞", "原子", "分子", "电子", "光子", "引力",
    "微积分", "代数", "几何", "统计", "概率",
    # 编程/技术
    "编程", "开发", "前端", "后端", "数据库", "服务器",
    "Python", "Java", "JavaScript", "C++", "Go", "Rust",
    "算法", "数据结构", "机器学习", "深度学习", "神经网络",
    "人工智能", "AI", "大模型", "LLM", "NLP", "计算机视觉",
    "Transformer", "BERT", "GPT", "卷积", "循环", "注意力机制",
    # 学术/教育
    "考试", "作业", "论文", "毕业", "考研", "留学",
    "英语", "单词", "听力", "口语", "写作", "翻译",
    "阅读理解", "完形填空", "四六级", "托福", "雅思", "GRE",
    "研究", "实验", "假设", "理论", "证据", "结论",
    "参考文献", "引用", "摘要", "引言", "方法论",
]


def _is_study_content(text: str) -> bool:
    """判断消息内容是否属于学习/知识性对话

    比 mode_detector.py 更宽泛，覆盖佛经、语言学、历史地理等话题。
    """
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in _STUDY_CONTENT_KEYWORDS)


def _detect_study_boundary(
    history: List[Dict[str, Any]],
    recent_window: int = 4,
) -> Optional[int]:
    """向后扫描找到学习→非学习的转换边界

    从倒数第 recent_window 条消息开始向前扫描，找到最后一个学习会话的起始位置。
    学习会话定义：连续的用户+assistant消息对，其中用户消息包含学习关键词。

    Returns:
        学习会话的起始索引，如果没有找到返回 None
    """
    if not history:
        return None
    n = len(history)
    if n <= recent_window:
        return None

    # 从 recent_window 之前开始扫描
    scan_end = n - recent_window
    if scan_end <= 0:
        return None

    # 标记每条消息是否是学习内容
    is_study = []
    for i in range(scan_end):
        msg = history[i]
        role = str(msg.get("role") or "").strip()
        content = str(msg.get("content") or "").strip()
        # 用户消息用关键词判断
        if role == "user":
            is_study.append(_is_study_content(content))
        else:
            # assistant 消息：
            # 1. 自身包含学习关键词
            # 2. 或前一条是学习内容，且当前消息非空（是有实质内容的回复）
            if _is_study_content(content):
                is_study.append(True)
            elif i > 0 and is_study[-1] and len(content) > 20:
                is_study.append(True)
            else:
                is_study.append(False)

    # 从后往前找最后一个学习会话的起始
    # 策略：找到最后一个连续学习块的起始位置
    boundary = None
    i = scan_end - 1
    while i >= 0:
        if is_study[i]:
            # 找到学习消息，继续向前找这个会话的起始
            boundary = i
            i -= 1
            while i >= 0 and is_study[i]:
                boundary = i
                i -= 1
            break
        i -= 1

    return boundary


def compress_study_session_messages(
    history: List[Dict[str, Any]],
    recent_window: int = 4,
    max_summary_chars: int = 600,
) -> List[Dict[str, Any]]:
    """压缩历史中的学习会话部分

    【设计原则】
    - 检测学习→非学习的边界
    - 将学习部分的消息替换为一条压缩摘要
    - 摘要保留学习主题和关键知识点
    - 不修改原始历史列表

    Args:
        history: 经过 sanitize 处理的历史消息列表
        recent_window: 最近保留原貌的消息数量
        max_summary_chars: 压缩摘要的最大字符数

    Returns:
        压缩后的历史消息列表（新列表）
    """
    if not history:
        return history

    boundary = _detect_study_boundary(history, recent_window)
    if boundary is None:
        return history

    n = len(history)
    study_end = n - recent_window

    # 提取学习部分的消息
    study_messages = history[boundary:study_end]
    if not study_messages:
        return history

    # 生成压缩摘要
    topics = []
    key_points = []
    total_chars = 0

    for msg in study_messages:
        role = str(msg.get("role") or "").strip()
        content = str(msg.get("content") or "").strip()
        total_chars += len(content)

        if role == "user" and len(content) < 100:
            # 短用户消息可能是学习问题
            if _is_study_content(content):
                topics.append(content[:50])
        elif role == "assistant" and len(content) > 200:
            # 长assistant消息提取首句作为关键点
            first_sentence = _extract_sentence_summary(content, 100)
            if first_sentence:
                key_points.append(first_sentence)

    # 生成摘要
    if not topics and not key_points:
        return history

    summary_parts = []
    if topics:
        summary_parts.append(f"讨论主题：{'、'.join(topics[:5])}")
    if key_points:
        summary_parts.append(f"关键知识点：{key_points[0]}")

    summary = "；".join(summary_parts)
    if len(summary) > max_summary_chars:
        summary = summary[:max_summary_chars - 3] + "..."

    compressed_content = f"[学习会话摘要] 之前进行了学习讨论（约{total_chars}字）：{summary}"

    # 构建压缩后的历史
    result = []
    # 学习会话之前的消息
    result.extend(history[:boundary])
    # 压缩摘要消息
    compressed_msg = {
        "role": "system",
        "content": compressed_content,
        "timestamp": study_messages[0].get("timestamp", 0),
    }
    result.append(compressed_msg)
    # 近期消息保持原样
    result.extend(history[study_end:])

    logger.info(
        "学习会话压缩：压缩 %d 条消息（约%d字）为摘要（%d字），节省约 %d 字符",
        len(study_messages), total_chars, len(compressed_content),
        total_chars - len(compressed_content),
    )

    return result


def apply_long_message_compression(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从配置读取参数，对历史消息中的旧长 assistant 消息进行压缩

    调用 condense_long_messages_in_history，配置项位于 ChatContextBudgetSettings。
    """
    if not history:
        return history
    threshold = 400
    recent_window = 6
    max_chars = 160
    try:
        from config.integrated_config import get_settings
        s = get_settings()
        chat = getattr(s, "chat", None)
        budget = getattr(chat, "context_budget", None) if chat is not None else None
        if budget is not None:
            threshold = safe_int(
                getattr(budget, "long_message_compress_threshold", threshold), threshold
            )
            recent_window = safe_int(
                getattr(budget, "long_message_compress_recent_window", recent_window),
                recent_window,
            )
            max_chars = safe_int(
                getattr(budget, "long_message_compress_max_chars", max_chars), max_chars
            )
    except Exception:
        pass
    return condense_long_messages_in_history(
        history=history,
        recent_window=recent_window,
        threshold_chars=threshold,
        max_summary_chars=max_chars,
    )


def apply_study_session_compression(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从配置读取参数，对历史中的学习会话进行压缩

    调用 compress_study_session_messages，配置项位于 ChatContextBudgetSettings。
    """
    if not history:
        return history
    enabled = True
    recent_window = 4
    max_chars = 600
    try:
        from config.integrated_config import get_settings
        s = get_settings()
        chat = getattr(s, "chat", None)
        budget = getattr(chat, "context_budget", None) if chat is not None else None
        if budget is not None:
            enabled = bool(getattr(budget, "study_session_compress_enabled", enabled))
            recent_window = safe_int(
                getattr(budget, "study_session_compress_recent_window", recent_window),
                recent_window,
            )
            max_chars = safe_int(
                getattr(budget, "study_session_compress_max_chars", max_chars),
                max_chars,
            )
    except Exception:
        pass
    if not enabled:
        return history
    return compress_study_session_messages(
        history=history,
        recent_window=recent_window,
        max_summary_chars=max_chars,
    )
