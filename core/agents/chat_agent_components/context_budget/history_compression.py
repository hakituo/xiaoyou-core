# -*- coding: utf-8 -*-
"""历史消息压缩（纯函数模块）。

职责：对历史消息列表做压缩，包括长消息摘要和学习会话压缩。
不依赖 memory_manager、不依赖外部 IO，纯 List[Dict] → List[Dict]。

被 history_fetch.py 调用，外部不直接使用。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_logger
from ._utils import safe_int

logger = get_logger("ChatAgent")


def _extract_sentence_summary(text: str, max_chars: int = 160) -> str:
    """从长文本中提取首句，用于低成本上下文压缩。"""
    s = str(text or "").strip()
    if not s:
        return ""
    m = re.match(r"^.{8,}?(?:[。！？!?\n])", s, re.DOTALL)
    if m:
        first_sentence = m.group(0).strip()
    else:
        first_sentence = s[: min(80, len(s))].strip()
    if len(first_sentence) > max_chars:
        first_sentence = first_sentence[: max_chars - 3].rstrip() + "..."
    return first_sentence


def _strip_history_prefix(text: str) -> str:
    """去掉上下文构建阶段附加的时间戳，避免摘要重复携带时间前缀。"""
    return re.sub(
        r"^(?:\[\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*)+",
        "",
        str(text or "").strip(),
    ).strip()


def _clip_text(text: str, max_chars: int) -> str:
    s = _strip_history_prefix(text)
    if len(s) <= max_chars:
        return s
    return s[: max(1, max_chars - 3)].rstrip() + "..."


def _append_unique(items: List[str], text: str, limit: int) -> None:
    value = str(text or "").strip()
    if not value or value in items or len(items) >= limit:
        return
    items.append(value)


def condense_long_messages_in_history(
    history: List[Dict[str, Any]],
    recent_window: int = 6,
    threshold_chars: int = 400,
    max_summary_chars: int = 160,
) -> List[Dict[str, Any]]:
    """压缩非近期窗口中的长 assistant 消息。

    只影响喂给 LLM 的副本，不修改短期记忆原文；最近 ``recent_window`` 条消息
    保持原貌。学习进行中会由 ``apply_long_message_compression`` 把该窗口扩大。
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

        if (
            i < n - recent_window
            and role == "assistant"
            and content_len > threshold_chars
        ):
            summary = _extract_sentence_summary(content, max_summary_chars)
            if summary:
                condensed_content = (
                    f"[上下文压缩] 之前详细回复（约{content_len}字）：{summary}"
                )
                entry = dict(msg)
                entry["content"] = condensed_content
                result.append(entry)
                compressed_count += 1
                saved_chars += content_len - len(condensed_content)
                continue

        result.append(msg)

    if compressed_count > 0:
        logger.info(
            "上下文长消息压缩：压缩 %d 条旧 assistant 消息，节省约 %d 字符"
            "（recent_window=%d, threshold=%d）",
            compressed_count,
            saved_chars,
            recent_window,
            threshold_chars,
        )

    return result


# ============================================================
# 学习会话检测与压缩
# ============================================================

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
    """判断消息文本是否明显属于学习/知识性对话。"""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in _STUDY_CONTENT_KEYWORDS)


def _message_study_flags(history: List[Dict[str, Any]]) -> List[bool]:
    """给历史消息打学习标记；优先使用落库的 learning 类别。"""
    flags: List[bool] = []
    for msg in history:
        category = str(msg.get("category") or "").strip().lower()
        role = str(msg.get("role") or msg.get("source") or "").strip().lower()
        content = str(msg.get("content") or "").strip()

        is_study = category == "learning" or _is_study_content(content)
        if not is_study and role == "assistant" and flags and flags[-1] and len(content) > 20:
            # assistant 紧接学习消息时，通常是对上一条问题的讲解。
            is_study = True
        flags.append(is_study)
    return flags


def _detect_completed_study_span(
    history: List[Dict[str, Any]],
    recent_window: int = 4,
    force: bool = False,
) -> Optional[Tuple[int, int]]:
    """找到最近一个已结束学习块，返回 ``[start, end)``。

    非强制模式要求学习块之后至少已有 ``recent_window`` 条非学习消息，避免正在
    学习时误压缩；显式退出学习模式时由调用方使用 ``force=True`` 立即收束。
    """
    if not history:
        return None

    flags = _message_study_flags(history)
    study_indexes = [i for i, value in enumerate(flags) if value]
    if not study_indexes:
        return None

    end = study_indexes[-1] + 1
    if not force and len(history) - end < max(1, int(recent_window)):
        return None

    start = end - 1
    while start > 0 and flags[start - 1]:
        start -= 1
    return start, end


def _span_from_timestamps(
    history: List[Dict[str, Any]],
    start_ts: Optional[float],
    end_ts: Optional[float],
) -> Optional[Tuple[int, int]]:
    """按显式学习会话 entered_at/exited_at 精确定位消息区间。"""
    if not history or not start_ts or not end_ts or end_ts < start_ts:
        return None

    indexes: List[int] = []
    for i, msg in enumerate(history):
        try:
            ts = float(msg.get("timestamp", 0) or 0)
        except (TypeError, ValueError):
            continue
        if ts > 0 and float(start_ts) <= ts <= float(end_ts):
            indexes.append(i)

    if not indexes:
        return None
    return indexes[0], indexes[-1] + 1


def _build_study_summary(
    study_messages: List[Dict[str, Any]],
    max_summary_chars: int,
) -> str:
    """构建面向后续对话的学习摘要，保留教学轨迹而非只取第一句。"""
    topics: List[str] = []
    key_points: List[str] = []
    user_trace: List[str] = []

    for msg in study_messages:
        role = str(msg.get("role") or msg.get("source") or "").strip().lower()
        content = _strip_history_prefix(str(msg.get("content") or ""))
        if not content:
            continue

        if role == "user":
            if _is_study_content(content):
                _append_unique(topics, _clip_text(content, 70), 5)
            _append_unique(user_trace, _clip_text(content, 120), 8)
        elif role == "assistant" and len(content) >= 40:
            point = _extract_sentence_summary(content, 130)
            _append_unique(key_points, point, 4)

    parts: List[str] = []
    if topics:
        parts.append("讨论主题：" + "、".join(topics[:5]))
    if key_points:
        parts.append("关键讲解：" + " / ".join(key_points[:3]))
    if user_trace:
        parts.append("用户最近问题/作答：" + " / ".join(user_trace[-3:]))

    summary = "；".join(parts).strip()
    if not summary:
        # 极短回答或题号可能没有关键词，至少保留最近几条学习轨迹。
        trail = []
        for msg in study_messages[-4:]:
            role = str(msg.get("role") or msg.get("source") or "").strip().lower()
            content = _clip_text(str(msg.get("content") or ""), 120)
            if content:
                trail.append(f"{role}: {content}")
        summary = "；".join(trail)

    if len(summary) > max_summary_chars:
        summary = summary[: max(1, max_summary_chars - 3)].rstrip() + "..."
    return summary


def compress_study_session_messages(
    history: List[Dict[str, Any]],
    recent_window: int = 4,
    max_summary_chars: int = 1200,
    *,
    force: bool = False,
    session_start_ts: Optional[float] = None,
    session_end_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """压缩已经结束的学习会话。

    显式学习模式退出时优先用 entered_at/exited_at 精确定位；没有显式会话信息时，
    仅在学习块之后已有足够非学习消息时才压缩，避免把仍在进行的教学工作记忆收掉。
    """
    if not history:
        return history

    span = _span_from_timestamps(history, session_start_ts, session_end_ts)
    if span is None:
        span = _detect_completed_study_span(
            history,
            recent_window=recent_window,
            force=force,
        )
    if span is None:
        return history

    start, end = span
    study_messages = history[start:end]
    if not study_messages:
        return history

    total_chars = sum(len(str(msg.get("content") or "")) for msg in study_messages)
    summary = _build_study_summary(study_messages, max_summary_chars=max_summary_chars)
    if not summary:
        return history

    compressed_content = (
        f"[学习会话摘要] 之前进行了学习讨论（约{total_chars}字）：{summary}"
    )
    compressed_msg = {
        "role": "system",
        "content": compressed_content,
        "timestamp": study_messages[0].get("timestamp", 0),
    }

    result = list(history[:start]) + [compressed_msg] + list(history[end:])
    logger.info(
        "学习会话压缩：压缩 %d 条消息（约%d字）为摘要（%d字），节省约 %d 字符",
        len(study_messages),
        total_chars,
        len(compressed_content),
        total_chars - len(compressed_content),
    )
    return result


def apply_long_message_compression(
    history: List[Dict[str, Any]],
    *,
    study_context_active: bool = False,
) -> List[Dict[str, Any]]:
    """按配置压缩旧长回复；学习进行中扩大原文保护窗口。"""
    if not history:
        return history

    threshold = 400
    recent_window = 6
    max_chars = 160
    study_active_recent_window = 20
    try:
        from config.integrated_config import get_settings

        settings = get_settings()
        chat = getattr(settings, "chat", None)
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
            study_active_recent_window = safe_int(
                getattr(
                    budget,
                    "study_active_recent_window",
                    study_active_recent_window,
                ),
                study_active_recent_window,
            )
    except Exception:
        pass

    if study_context_active:
        recent_window = max(recent_window, study_active_recent_window)

    return condense_long_messages_in_history(
        history=history,
        recent_window=recent_window,
        threshold_chars=threshold,
        max_summary_chars=max_chars,
    )


def apply_study_session_compression(
    history: List[Dict[str, Any]],
    *,
    force: bool = False,
    session_start_ts: Optional[float] = None,
    session_end_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """按配置压缩已经结束的学习会话。"""
    if not history:
        return history

    enabled = True
    recent_window = 4
    max_chars = 1200
    try:
        from config.integrated_config import get_settings

        settings = get_settings()
        chat = getattr(settings, "chat", None)
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
        force=force,
        session_start_ts=session_start_ts,
        session_end_ts=session_end_ts,
    )
