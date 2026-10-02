"""
学习模式工具

AI可以主动调用进入/退出学习模式，系统会相应地：
- 注入学习模式prompt
- 触发学习会话压缩（退出时）

设计约束（2026-09-21 修复）：
历史上 ``enter_study_mode`` 的工具描述过宽（"讨论学术话题时调用"），
导致模型在普通闲聊里随口提到专业名词就自行进入学习模式，并且因为
会话状态只存在内存、没有过期机制，进去后就再也退不出来（用户案例：
聊安卓开发被判定成"学科=物理 主题=费米能级"）。

现在本模块做了三件事：
1. 收紧工具描述与入参，明确只在"用户明确要求系统性地学/讲某个知识"时才调用；
2. 给会话状态补上 ``turn_count`` / ``last_signal_at``，由调用方每轮喂入；
3. 提供 ``tick_study_session`` 自动退出：连续多轮没有学习信号、或超过 TTL、
   或达到轮次上限时自动退出，不再依赖模型自己记得调用 exit。

所有阈值都可通过 ``config/yaml/app.yaml`` 的 ``study_mode`` 分节配置，
不写死在代码里。

工具列表：
- EnterStudyModeTool: 进入学习模式
- ExitStudyModeTool: 退出学习模式
"""
from __future__ import annotations
from core.utils.logger import get_logger

import time

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from core.tools.base import BaseTool

logger = get_logger("Tools.StudyMode")

# 学习会话存储（按用户隔离）
_study_sessions: Dict[str, dict] = {}


# ---------------------------------------------------------------------------
# 可配置阈值
# ---------------------------------------------------------------------------

# 默认值集中在这里，便于测试与文档引用；实际读取见 _study_cfg。
_DEFAULT_TTL_SECONDS = 3 * 3600.0        # 单次学习会话最长存活 3 小时
_DEFAULT_MAX_TURNS = 60                  # 最多连续 60 轮，超出自动退出
_DEFAULT_IDLE_TURNS = 6                  # 连续 6 轮无学习信号自动退出
_DEFAULT_IDLE_SECONDS = 30 * 60.0        # 或无学习信号满 30 分钟自动退出


def _study_cfg(key: str, default: Any) -> Any:
    """读取 ``life_simulation.study_mode.<key>`` 配置。

    【路径说明】必须显式拼 ``study_mode.`` 子前缀：yaml 里这些键放在
    ``life_simulation.study_mode.*`` 下，而 ``get_active_care_config`` 只会
    自动补 ``life_simulation.`` 这一层。早期版本漏了子前缀，导致 yaml 改不动、
    永远走代码默认值。

    配置读取失败时静默回退到默认值——学习模式是辅助能力，
    不能因为配置模块异常而阻断对话主流程。
    """
    try:
        from core.utils.config_accessor import get_config

        return get_config(f"life_simulation.study_mode.{key}", default=default)
    except Exception:
        return default


def _cfg_float(key: str, default: float) -> float:
    try:
        return float(_study_cfg(key, default))
    except (TypeError, ValueError):
        return default


def _cfg_int(key: str, default: int) -> int:
    try:
        return int(_study_cfg(key, default))
    except (TypeError, ValueError):
        return default


def get_study_session_limits() -> Dict[str, Any]:
    """返回当前生效的学习会话限制（供验证脚本与调试使用）。"""
    return {
        "ttl_seconds": _cfg_float("study_mode_session_ttl_seconds", _DEFAULT_TTL_SECONDS),
        "max_turns": _cfg_int("study_mode_max_turns", _DEFAULT_MAX_TURNS),
        "idle_turns": _cfg_int("study_mode_idle_turns", _DEFAULT_IDLE_TURNS),
        "idle_seconds": _cfg_float("study_mode_idle_seconds", _DEFAULT_IDLE_SECONDS),
    }


# ---------------------------------------------------------------------------
# 状态查询
# ---------------------------------------------------------------------------

def is_study_mode_active(user_id: str) -> bool:
    """检查用户是否处于学习模式"""
    session = _study_sessions.get(str(user_id).strip())
    return bool(session and session.get("active"))


def get_study_session(user_id: str) -> Optional[dict]:
    """获取学习会话信息"""
    return _study_sessions.get(str(user_id).strip())


def get_study_prompt_for_injection(user_id: str) -> Optional[str]:
    """获取当前用户应注入的学习模式prompt"""
    session = _study_sessions.get(str(user_id).strip())
    if not session or not session.get("active"):
        return None

    subject = session.get("subject", "")
    topic = session.get("topic", "")

    # 基础学习模式prompt
    prompt = _STUDY_MODE_PROMPT

    # 如果指定了学科/主题，添加专门的指导
    if subject:
        prompt += f"\n\n当前学习学科：{subject}"
    if topic:
        prompt += f"\n当前学习主题：{topic}"

    return prompt


# ---------------------------------------------------------------------------
# 状态写入
# ---------------------------------------------------------------------------

def _set_study_state(user_id: str, active: bool, subject: str = "", topic: str = ""):
    """设置学习模式状态"""
    uid = str(user_id).strip()
    now = time.time()
    if active:
        _study_sessions[uid] = {
            "active": True,
            "subject": subject,
            "topic": topic,
            "entered_at": now,
            "last_signal_at": now,
            "turn_count": 0,
            "idle_turn_count": 0,
            "exit_reason": "",
        }
        logger.info(f"用户 {uid} 进入学习模式 subject={subject} topic={topic}")
    else:
        session = _study_sessions.get(uid)
        if session:
            session["active"] = False
            session["exited_at"] = now
            logger.info(f"用户 {uid} 退出学习模式")


def _exit_with_reason(user_id: str, reason: str) -> Optional[dict]:
    """带原因地退出学习模式，返回退出时的会话快照。"""
    uid = str(user_id).strip()
    session = _study_sessions.get(uid)
    if not session or not session.get("active"):
        return None
    _set_study_state(uid, False)
    session = _study_sessions.get(uid) or {}
    session["exit_reason"] = reason
    logger.info(f"用户 {uid} 学习模式自动退出，原因={reason}")
    return session


def tick_study_session(user_id: str, has_learning_signal: bool) -> Optional[dict]:
    """每轮对话调用一次，推进学习会话计数并在需要时自动退出。

    这是"模型忘了退"问题的兜底：学习模式不再是一次进入就永久生效，
    而是必须持续有学习信号才续命。

    Args:
        user_id: 用户 ID
        has_learning_signal: 本轮消息是否检测到学习信号
            （复用 core.services.study.mode_detector 的规则检测结果）

    Returns:
        自动退出时的会话快照（含 ``exit_reason``）；未退出返回 None。
    """
    uid = str(user_id).strip()
    session = _study_sessions.get(uid)
    if not session or not session.get("active"):
        return None

    limits = get_study_session_limits()
    now = time.time()

    session["turn_count"] = int(session.get("turn_count") or 0) + 1

    if has_learning_signal:
        session["last_signal_at"] = now
        session["idle_turn_count"] = 0
    else:
        session["idle_turn_count"] = int(session.get("idle_turn_count") or 0) + 1

    # 1. 轮次上限：防止长会话被永久标记为学习
    max_turns = limits["max_turns"]
    if max_turns > 0 and session["turn_count"] >= max_turns:
        return _exit_with_reason(uid, f"达到轮次上限({max_turns})")

    # 2. TTL：防止进程长时间运行后状态残留
    ttl = limits["ttl_seconds"]
    entered_at = float(session.get("entered_at") or now)
    if ttl > 0 and (now - entered_at) >= ttl:
        return _exit_with_reason(uid, f"超过会话时长上限({int(ttl)}s)")

    # 3. 空闲轮次 / 空闲时长：话题漂移检测，连续无学习信号即退出
    idle_turns = limits["idle_turns"]
    if idle_turns > 0 and session["idle_turn_count"] >= idle_turns:
        return _exit_with_reason(uid, f"连续{idle_turns}轮无学习信号")

    idle_seconds = limits["idle_seconds"]
    last_signal_at = float(session.get("last_signal_at") or entered_at)
    if idle_seconds > 0 and (now - last_signal_at) >= idle_seconds:
        return _exit_with_reason(uid, f"无学习信号已满{int(idle_seconds)}s")

    return None


def reset_study_sessions() -> None:
    """清空全部学习会话（仅用于测试）。"""
    _study_sessions.clear()


# 学习模式prompt
_STUDY_MODE_PROMPT = """【学习模式已激活】

你现在处于教学/学习辅助模式。请遵循以下原则：

1. **知识准确性优先**：回答要准确、有依据，不要猜测或编造
2. **循序渐进**：根据用户水平调整解释深度，从基础开始逐步深入
3. **引导思考**：不要直接给答案，引导用户自己思考（适当情况下）
4. **举例说明**：用具体例子帮助理解抽象概念
5. **结构化输出**：使用标题、列表、代码块等格式让内容更清晰
6. **鼓励提问**：欢迎用户追问，耐心解答每一个问题

【注意】
- 这是学习场景，请保持专业、耐心的态度
- 如果涉及专业知识，尽量引用来源或说明依据
- 退出学习模式时，我会自动压缩学习过程中的长上下文
"""


class EnterStudyModeInput(BaseModel):
    """进入学习模式参数"""
    subject: str = Field(
        default="",
        description="学习学科（可选），如：佛学、印度历史、Python编程"
    )
    topic: str = Field(
        default="",
        description="具体学习主题（可选），如：般若心经、莫卧儿帝国、装饰器"
    )


class EnterStudyModeTool(BaseTool):
    name = "enter_study_mode"
    description = (
        "进入学习模式。仅当用户【明确要求】系统性地学习/讲解某个知识主题时调用，"
        "例如「给我讲讲莫卧儿帝国」「教我推导一下傅里叶变换」「我准备学佛学，从般若心经开始」。\n"
        "以下情况【禁止调用】：\n"
        "- 普通闲聊、吐槽、日常分享；\n"
        "- 只是随口提到某个专业名词或行业概念（如聊工作时提到「变频器」「半导体」）；\n"
        "- 用户在教你、或你们在平等讨论某话题；\n"
        "- 用户只是问一个单点事实问题（直接回答即可）。\n"
        "subject/topic 必须来自用户原话，不允许自己推断或脑补。"
        "不确定时不要调用。"
    )
    short_description = "进入学习模式，优化教学场景"
    args_schema = EnterStudyModeInput
    category = "study"
    enabled_by_default = True

    async def _run(self, subject: str = "", topic: str = "") -> str:
        user_id = self._get_ctx("user_id", "default")

        # 修正模型自行编造学科/主题的问题：只接受来自用户消息的原文词。
        subject, topic = _sanitize_subject_topic(
            subject, topic, self._get_ctx("last_user_text", "")
        )

        # 如果已经在学习模式，更新主题
        if is_study_mode_active(user_id):
            session = get_study_session(user_id)
            if subject and subject != session.get("subject"):
                _set_study_state(user_id, True, subject, topic)
                return f"已更新学习主题：学科={subject}, 主题={topic}"
            return "已经在学习模式中"

        _set_study_state(user_id, True, subject, topic)

        subject_str = f"（学科：{subject}）" if subject else ""
        topic_str = f"（主题：{topic}）" if topic else ""
        return f"已进入学习模式{subject_str}{topic_str}。我会以更专业、耐心的方式协助你学习。退出学习模式时会自动压缩学习过程的长上下文。"


class ExitStudyModeInput(BaseModel):
    """退出学习模式参数"""
    reason: str = Field(
        default="",
        description="退出原因（可选），如：学完了、换个话题、休息一下"
    )


class ExitStudyModeTool(BaseTool):
    name = "exit_study_mode"
    description = (
        "退出学习模式。当用户表示学完了、要切换话题、或想休息时调用。"
        "系统会自动压缩学习过程中的长上下文以节省token。"
    )
    short_description = "退出学习模式，压缩学习上下文"
    args_schema = ExitStudyModeInput
    category = "study"
    enabled_by_default = True

    async def _run(self, reason: str = "") -> str:
        user_id = self._get_ctx("user_id", "default")

        if not is_study_mode_active(user_id):
            return "当前不在学习模式"

        session = get_study_session(user_id)
        subject = session.get("subject", "")
        duration = time.time() - session.get("entered_at", time.time())
        duration_min = round(duration / 60, 1)

        _set_study_state(user_id, False)

        # 学习会话压缩会在context_budget.py中自动触发（通过检测学习→非学习边界）

        reason_str = f"（原因：{reason}）" if reason else ""
        subject_str = f"学科：{subject}，" if subject else ""
        return f"已退出学习模式{reason_str}。{subject_str}学习时长：{duration_min}分钟。学习过程中的长上下文会在下次构建时自动压缩。"


def _sanitize_subject_topic(subject: str, topic: str, user_text: str = "") -> tuple:
    """约束 subject/topic 只能来自用户原话，避免模型自行脑补学科。

    历史缺陷：用户聊安卓开发时，模型自行填写 ``subject=物理 topic=费米能级``。
    这里用当前会话最近一条用户消息做一次包含校验；拿不到原话时清空字段，
    宁可不标注学科，也不写一个编造的学科。

    Args:
        subject: 模型给出的学科
        topic: 模型给出的主题
        user_text: 当前会话最近一条用户消息原文（由运行时上下文注入）

    Returns:
        (subject, topic) 清洗后的值
    """
    subj = str(subject or "").strip()
    topi = str(topic or "").strip()
    if not subj and not topi:
        return "", ""

    text = str(user_text or "").strip()
    # 拿不到用户原话：保守清空，避免把编造的学科写进会话
    if not text:
        if subj or topi:
            logger.info("学习模式：拿不到用户原话，清空模型给出的 subject/topic")
        return "", ""

    if subj and subj not in text:
        logger.info("学习模式：subject=%s 不在用户原话中，已清空", subj)
        subj = ""
    if topi and topi not in text:
        logger.info("学习模式：topic=%s 不在用户原话中，已清空", topi)
        topi = ""
    return subj, topi
