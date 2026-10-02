"""日记服务共享工具函数

从 core/services/journal/service.py 拆分出来的工具函数和常量，
供 JournalService 门面、JournalSummaryService、JournalPlanService、
SummaryContextLoader、PlanCRUDService 共享使用。

设计原则：
- 纯函数 / 无状态工具，不依赖 service 实例
- 接收所需依赖（settings 等）作为参数，避免循环引用
"""
import asyncio
import re
from datetime import datetime
from functools import partial
from typing import Any, Dict, List, Optional, Tuple, Union

from core.utils.logger import get_logger
from core.utils.time_utils import get_diary_target_date, ts_to_str
from core.services.scheduler.task.task_scheduler import get_global_scheduler
from core.services.journal.diary_personas import (
    get_diary_display_name,
    get_diary_persona_ids,
    get_diary_peer_ids,
    get_diary_user_label,
)
from core.services.journal.models import JournalEntry

logger = get_logger("JournalService")


# 技术细节过滤模式：移除文件名、模型名、错误类型等系统信息
TECHNICAL_PATTERNS = (
    ".py", ".json", ".log", ".md",
    "Error", "Exception", "Traceback", "ImportError",
    "_client", "_module", "_service", "_manager",
    "siliconflow", "deepseek", "openai", "qwen",
    "HTTP", "SSL", "TCP", "API",
    "patch", "补丁", "修复补丁",
)

# ── 计划项枚举校验常量 ─────────────────────────────────────
WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
VALID_SUBJECTS = {"语文", "数学", "英语", "物理", "化学", "生物"}
VALID_CATEGORIES = {"study", "life", "rest", "other"}
VALID_PRIORITIES = {"high", "normal", "low"}
VALID_STATUSES = {"pending", "in_progress", "completed", "skipped"}


# ── 用户日记读取 ─────────────────────────────────────────────

def load_user_diary_from_study(date: datetime) -> str:
    """从 D:\\AI\\Study\\Daily/YYYY/MM/DD/diary.md 读取用户手写的日记

    返回日记内容文本；文件不存在或为空时返回空字符串。
    """
    try:
        from core.utils.data_paths import get_study_daily_date_dir
        diary_path = get_study_daily_date_dir(date) / "diary.md"
        if not diary_path.exists():
            return ""
        content = diary_path.read_text(encoding="utf-8").strip()
        # 去掉标题行（如 "# 2026-06-22 日记"）
        lines = content.split("\n")
        body_lines = [
            line for line in lines
            if not line.strip().startswith("#")
        ]
        body = "\n".join(body_lines).strip()
        return body
    except Exception as e:
        logger.warning(f"读取用户日记失败: {e}")
        return ""


# ── 日记条目 / 记忆相关 ───────────────────────────────────

def normalize_source(entry: JournalEntry) -> str:
    """规范化 entry.source 字段为小写字符串"""
    return str(entry.source or "").strip().lower()


def should_skip_memory_append(entry: JournalEntry, settings: Any) -> bool:
    """判断该日记条目是否应跳过写入记忆系统

    规则：
    - 自动生成的每日总结：受 append_auto_daily_summary_to_user_journal 开关控制
    - AI 主动写的日记（source 为 aveline/ling）：受 append_user_journal_to_memory 开关控制
    - 兼容旧的 user source：同上开关
    """
    source = normalize_source(entry)
    thought = str(entry.thought or "").strip().lower()
    # 自动生成的每日总结
    if thought == "auto_generated_daily_summary":
        if not getattr(settings.memory, "append_auto_daily_summary_to_user_journal", False):
            return True
    # AI 主动写的日记（source 为任一注册角色）
    if source in get_diary_persona_ids():
        if not getattr(settings.memory, "append_user_journal_to_memory", False):
            return True
    # 兼容旧的 user source
    if source == "user":
        if not getattr(settings.memory, "append_user_journal_to_memory", False):
            return True
    return False


def parse_date(date_str: Optional[str]) -> datetime:
    """解析日期字符串；未提供时走统一凌晨归属逻辑"""
    if not date_str:
        return get_diary_target_date()
    try:
        if " " in date_str:
            date_str = date_str.split(" ")[0]
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning(f"Invalid date format {date_str}, using diary target date")
        return get_diary_target_date()


def get_journal_model_hint(settings: Any) -> str:
    """获取日记专用模型 hint

    优先从 config.model_config.get_journal_model() 获取，
    回退到 settings.model.journal_model_hint。
    """
    try:
        from config.model_config import get_journal_model
        hint = get_journal_model()
        if hint:
            return hint
    except Exception:
        pass
    return str(getattr(settings.model, "journal_model_hint", "") or "").strip()


async def call_llm_stream(
    messages: Union[str, List[Dict[str, str]]],
    settings: Any,
    max_tokens: int = 600,
    temperature: float = 0.3,
    model_hint: str = "",
) -> str:
    """调用 LLM，支持单字符串 prompt 或 system+user 消息列表

    最多重试 3 次，每次失败后指数退避（2 * (attempt + 1) 秒）。
    返回空字符串表示所有重试均失败。
    """
    scheduler = get_global_scheduler()
    resolved_model_hint = model_hint or get_journal_model_hint(settings)

    for attempt in range(3):
        raw_out = ""
        try:
            async for chunk in scheduler.submit_llm_task(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                model_hint=resolved_model_hint,
            ):
                if isinstance(chunk, str):
                    raw_out += chunk
                elif isinstance(chunk, dict) and chunk.get("content"):
                    raw_out += str(chunk.get("content") or "")
        except Exception as e:
            logger.warning(f"Journal LLM 调用异常 (attempt {attempt + 1}): {e}")
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            return ""

        if raw_out.strip():
            return raw_out

        logger.warning(f"Journal LLM 返回空内容 (attempt {attempt + 1})")
        if attempt < 2:
            await asyncio.sleep(2 * (attempt + 1))

    return ""


def filter_technical_details(text: str) -> str:
    """过滤掉技术细节，只保留角色视角的行为描述

    - 移除文件路径（xxx.py 之类）
    - 移除技术术语（错误类型、模型名、协议名等）
    - 清理多余空格
    """
    # 移除文件路径
    text = re.sub(r'[\w/\\]+\.\w{1,5}', '', text)
    # 移除技术术语
    for pattern in TECHNICAL_PATTERNS:
        text = text.replace(pattern, '')
    # 清理多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def build_study_digest_text(study_stats: Dict[str, Any]) -> str:
    """构建学习摘要文本（用于每日总结追加学习总结段落）"""
    payload = study_stats or {}
    vocab = payload.get("vocab") or {}
    overview = payload.get("overview") or {}
    reviewed = int(vocab.get("to_review") or 0)
    sessions = int(overview.get("total_sessions") or 0)
    top_subjects = [
        str(s).strip()
        for s in (overview.get("top_subjects") or [])
        if str(s).strip()
    ]
    subject_text = "、".join(top_subjects[:3]) if top_subjects else "综合练习"
    if reviewed <= 0 and sessions <= 0:
        return ""
    return f"学习侧重点：{subject_text}；复习目标 {reviewed} 项；学习记录 {sessions} 次。"


def append_weighted_memory(entry: JournalEntry, settings: Any) -> None:
    """同步写入加权记忆（在 executor 线程中调用）

    供 JournalService._append_journal_memory 通过 asyncio.to_thread 调用。
    """
    from memory.weighted_memory_manager import get_weighted_memory_manager

    memory_content = f"[{entry.time_str}] ({entry.type}) {entry.content}"
    source = normalize_source(entry)
    target_conversation_id = "default_user"
    if source == "active_care" or source in get_diary_persona_ids():
        target_conversation_id = source
    manager = get_weighted_memory_manager(target_conversation_id)
    if not manager:
        return
    metadata: Dict[str, Any] = {
        "mood": entry.mood,
        "thought": entry.thought,
        "source": entry.source,
        "tags": entry.tags,
        "entry_type": entry.type,
    }
    manager.add_memory(
        content=memory_content,
        source="journal",
        category="diary",
        topics=["journal", "workspace", entry.type],
        metadata=metadata,
    )


# 保留 partial 的引用，方便 _append_journal_memory 使用
get_weighted_memory_manager_partial = partial


# ── 每日总结上下文格式化 ───────────────────────────────────

def format_diary_context(
    entries: List[JournalEntry], persona: str = "aveline"
) -> str:
    """格式化可用于角色日记生成的原始片段。

    这里只允许主人手写条目和当前角色自己的非自动片段。自动生成的每日
    总结以及另一个角色的条目必须排除，防止 nightly 多次运行后互相抄写。
    """
    texts = []
    for e in entries:
        entry_type = str(e.type or "").strip().lower()
        thought = str(e.thought or "").strip().lower()
        source = normalize_source(e)
        if entry_type == "daily_summary" or thought == "auto_generated_daily_summary":
            continue
        if source not in {"user", persona}:
            continue

        owner = "主人手记" if source == "user" else "我的随手记"
        text = f"[{e.time_str}] ({owner}/{entry_type or 'daily'}) {e.content}"
        if e.thought:
            text += f"\n(Thought: {e.thought})"
        texts.append(text)
    return "\n\n".join(texts) if texts else "今天没有可用的手写日记片段。"


def format_chat_context(chat_history: List[Dict[str, Any]], persona: str = "aveline") -> str:
    """格式化聊天历史为文本，按 persona 取角色自称与对主人的称呼。

    标签一律来自注册角色画像，不再硬编码 Aveline / Ling。
    """
    lines = []
    user_label = get_diary_user_label(persona)
    assistant_label = get_diary_display_name(persona)
    for msg in chat_history:
        ts = float(msg.get("timestamp") or 0.0)
        time_str = ts_to_str(ts, "%H:%M:%S") if ts > 0 else "--:--:--"
        role = user_label if str(msg.get("role")) == "user" else assistant_label
        content = str(msg.get("content") or "").strip()
        if len(content) > 180:
            content = content[:180] + "..."
        lines.append(f"[{time_str}] {role}: {content}")
    return "\n".join(lines) if lines else "无有效聊天历史。"


def format_active_care_context(events: List[Dict[str, Any]]) -> str:
    """格式化主动关怀事件为文本，过滤技术细节"""
    lines = []
    for event in events:
        time_str = str(event.get("time") or "").strip() or "--:--:--"
        event_type = str(event.get("event_type") or "unknown").strip()
        content = str(event.get("content") or "").strip()
        # 过滤技术细节，只保留角色视角
        content = filter_technical_details(content)
        if not content:
            continue
        if len(content) > 180:
            content = content[:180] + "..."
        lines.append(f"[{time_str}] ({event_type}) {content}")
    return "\n".join(lines) if lines else "今天还没有主动关怀行为记录。"


def format_peer_chat_context(peer_history: List[Dict[str, Any]], persona: str = "aveline") -> str:
    """格式化角色互聊记录，按 persona 翻转角色标记。

    peer chat 数据中 user=Ling, assistant=Aveline（Aveline）。
    没有互识关系的角色（Ye等单角色）不注入别人的互聊记录 —— 写了就是 OOC。
    """
    peer_ids = get_diary_peer_ids(persona)
    if not peer_ids:
        return ""
    peer_name = get_diary_display_name(peer_ids[0])
    if not peer_history:
        return f"今天没有和{peer_name}的互动记录。"
    lines = []
    for msg in peer_history:
        ts = float(msg.get("timestamp") or 0.0)
        time_str = ts_to_str(ts, "%H:%M") if ts > 0 else "--:--"
        role = str(msg.get("role") or msg.get("sender") or "unknown")
        if persona == "aveline":
            if role == "user":
                role = peer_name
            elif role == "assistant":
                role = "我"  # Aveline就是 Aveline
        else:  # 互聊里 user 侧的那个角色（Ling）
            if role == "user":
                role = "我"
            elif role == "assistant":
                role = get_diary_display_name("aveline")
        content = str(msg.get("content") or "").strip()
        if len(content) > 120:
            content = content[:120] + "..."
        lines.append(f"[{time_str}] {role}: {content}")
    return "\n".join(lines)


def format_character_daily_context(character_daily: Dict[str, Any], persona: str = "aveline") -> str:
    """格式化角色日常活动上下文（自然描述，非流水账）

    Args:
        character_daily: 从 SummaryContextLoader.load_character_daily_activities 获取的数据
        persona: 当前生成日记的角色视角

    Returns:
        自然语言描述的活动摘要，供 LLM 参考但不直接照抄
    """
    if not character_daily:
        return ""

    parts = []
    
    # 当前角色的活动摘要
    role_data = character_daily.get(persona)
    if role_data and role_data.get("activities"):
        activities = role_data["activities"]
        
        # 统计活动类型
        completed = [a for a in activities if a.get("status") == "completed"]
        ongoing = [a for a in activities if a.get("status") == "ongoing"]
        
        # 提取主要活动（去重）
        unique_activities = list(set(a.get("activity") for a in completed))
        
        if unique_activities:
            # 用更自然的方式描述
            if len(unique_activities) <= 2:
                activity_desc = "和".join(unique_activities)
            else:
                activity_desc = "、".join(unique_activities[:3]) + "等"
            parts.append(f"今天主要在{activity_desc}")
        
        if ongoing:
            current = ongoing[0].get("verb", "")
            if current:
                parts.append(f"现在正在{current}")
        
        peer_count = role_data.get("peer_chat_count", 0)
        peer_ids = get_diary_peer_ids(persona)
        if peer_count > 0 and peer_ids:
            parts.append(f"和{get_diary_display_name(peer_ids[0])}聊了几次天")

    # 互识角色的简要状态（没有互识关系的角色不注入别人的生活）
    peer_ids = get_diary_peer_ids(persona)
    for other_role in peer_ids:
        other_data = character_daily.get(other_role)
        if not (other_data and other_data.get("activities")):
            continue
        activities = other_data["activities"]
        if not activities:
            continue
        # 取最新的活动
        verb = activities[-1].get("verb", "")
        if verb:
            parts.append(f"{get_diary_display_name(other_role)}刚{verb}")

    return "，".join(parts) if parts else ""


def _resolve_diary_prompt_templates(persona: str) -> Tuple[str, str]:
    """按 persona 取 (system_prompt, user_template)。

    专属模板按角色注册；注册了但没有专属模板的角色走通用模板，
    用权威画像里的名字拼身份边界，绝不串到别的角色语气上。
    """
    from core.agents.chat_agent_components.persona_system.prompt.components import (
        GENERIC_DAILY_SUMMARY_SYSTEM_PROMPT_TEMPLATE,
        GENERIC_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
        JOURNAL_DAILY_SUMMARY_SYSTEM_PROMPT,
        JOURNAL_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
        LING_DAILY_SUMMARY_SYSTEM_PROMPT,
        LING_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
        YE_DAILY_SUMMARY_SYSTEM_PROMPT,
        YE_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
    )

    normalized = str(persona or "").strip().lower()
    routes = {
        "aveline": (
            JOURNAL_DAILY_SUMMARY_SYSTEM_PROMPT,
            JOURNAL_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
        ),
        "ling": (
            LING_DAILY_SUMMARY_SYSTEM_PROMPT,
            LING_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
        ),
        "ye": (
            YE_DAILY_SUMMARY_SYSTEM_PROMPT,
            YE_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
        ),
    }
    matched = routes.get(normalized)
    if matched is not None:
        return matched

    from core.services.journal.diary_personas import (
        get_diary_persona_name,
        get_diary_peer_ids,
    )

    self_name = get_diary_persona_name(normalized)
    peers = [get_diary_persona_name(peer) for peer in get_diary_peer_ids(normalized)]
    peer_boundary = f"，{'、'.join(peers)}说过做过的事也属于他们" if peers else ""
    logger.warning(
        "角色 %s 没有专属日记 prompt，使用通用模板（角色名来自权威画像）", normalized
    )
    return (
        GENERIC_DAILY_SUMMARY_SYSTEM_PROMPT_TEMPLATE.format(
            self_name=self_name, peer_boundary=peer_boundary
        ),
        GENERIC_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
    )


def _resolve_diary_sensitive_prefix(persona: str) -> str:
    """敏感人设的日记 system prompt 前置层（非敏感人设返回空串）。

    直接复用聊天侧的 `select_sensitive_prefix(persona_filename)`，
    不在这里另写一份判断，避免"日记一套、聊天一套"。
    """
    try:
        from core.agents.chat_agent_components.persona_system.prompt.sensitive_prefix import (
            select_sensitive_prefix,
        )
        from core.services.dual_role.personas import get_persona

        profile = get_persona(persona)
        filename = str(
            (profile.config_filename if profile else "") or persona or ""
        ).strip()
        return select_sensitive_prefix(filename)
    except Exception as exc:  # noqa: BLE001 - 前缀层缺失不能阻断日记生成
        logger.warning("读取敏感人设日记前缀失败 persona=%s: %s", persona, exc)
        return ""


def build_daily_summary_messages(
    date_str: str,
    diary_context: str,
    chat_context: str,
    active_care_context: str,
    user_status_summary: str,
    study_context: str,
    daily_context: str,
    peer_chat_context: str = "",
    persona: str = "aveline",
    user_diary_context: str = "",
    character_daily_context: str = "",
) -> List[Dict[str, str]]:
    """返回 system + user 分离的消息列表，根据 persona 选择对应 prompt 模板。

    敏感人设（如Ye）复用主对话的分级前缀层，插在 system 最前面，
    与聊天时的口径一致（同一份 sensitive_prefix.txt 正文、同一选择规则）。
    """
    system_prompt, user_template = _resolve_diary_prompt_templates(persona)
    sensitive_prefix = _resolve_diary_sensitive_prefix(persona)
    if sensitive_prefix:
        from core.agents.chat_agent_components.persona_system.prompt.fixed_prefix import (
            prepend_fixed_prefix,
        )

        system_prompt = prepend_fixed_prefix(system_prompt, sensitive_prefix)
    user_prompt = user_template.format(
        date_str=date_str,
        diary_context=diary_context,
        chat_context=chat_context,
        active_care_context=active_care_context,
        user_status_summary=user_status_summary,
        study_context=study_context,
        daily_context=daily_context,
        peer_chat_context=peer_chat_context,
        user_diary_context=user_diary_context or "主人今天还没有写日记。",
        character_daily_context=character_daily_context or "无角色日常活动数据。",
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ── 计划项规范化与格式化 ───────────────────────────────────

def normalize_plan_item_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    """规范化 LLM 输出的计划项字典（去掉系统字段、补默认值）"""
    clean = {
        "time": str(raw.get("time") or "").strip() or None,
        "title": str(raw.get("title") or "").strip(),
        "description": str(raw.get("description") or "").strip() or None,
        "category": str(raw.get("category") or "study").strip(),
        "subject": str(raw.get("subject") or "").strip() or None,
        "priority": str(raw.get("priority") or "normal").strip(),
        "estimated_duration_minutes": int(raw.get("estimated_duration_minutes") or 60),
    }
    # 校验枚举值
    if clean["category"] not in VALID_CATEGORIES:
        clean["category"] = "study"
    if clean["priority"] not in VALID_PRIORITIES:
        clean["priority"] = "normal"
    # 非 study 类别清空 subject
    if clean["category"] != "study":
        clean["subject"] = None
    elif clean["subject"] and clean["subject"] not in VALID_SUBJECTS:
        # 学科不在标准列表里，保留但记日志
        logger.warning(f"非标准学科: {clean['subject']}")
    # 校验 time 格式 HH:MM
    if clean["time"]:
        try:
            h, m = clean["time"].split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError
        except Exception:
            logger.warning(f"无效的 time 格式: {clean['time']}，置空")
            clean["time"] = None
    if not clean["title"]:
        clean["title"] = "未命名计划项"
    return clean


def format_yesterday_for_plan(ctx: Dict[str, Any]) -> str:
    """把昨日学习记录格式化为给 LLM 看的文本"""
    parts = []
    # 学习统计
    stats = ctx.get("study_stats") or {}
    overview = stats.get("overview") or {}
    vocab = stats.get("vocab") or {}
    if overview or vocab:
        total_sessions = int(overview.get("total_sessions") or 0)
        total_minutes = int(overview.get("total_minutes") or 0)
        parts.append(f"学习时长：{total_minutes} 分钟，共 {total_sessions} 次记录")
        top_subjects = overview.get("top_subjects") or []
        if top_subjects:
            parts.append(f"主要学科：{'、'.join(str(s) for s in top_subjects[:6])}")
        reviewed = int(vocab.get("to_review") or 0)
        if reviewed > 0:
            parts.append(f"待复习项：{reviewed}")
    # 日记摘要
    summary = ctx.get("daily_summary")
    if summary and summary.summary:
        parts.append(f"日记总结：{summary.summary[:300]}")
        if summary.tomorrow_tone:
            parts.append(f"明日基调建议：{summary.tomorrow_tone[:200]}")
    # 日记条目（取前 5 条）
    entries = ctx.get("diary_entries") or []
    if entries:
        entry_texts = []
        for e in entries[:5]:
            t = f"[{e.time_str}] {e.content[:120]}"
            if e.thought:
                t += f"（{e.thought[:60]}）"
            entry_texts.append(t)
        parts.append("日记条目：\n" + "\n".join(entry_texts))
    return "\n".join(parts) if parts else "昨日无学习记录"
