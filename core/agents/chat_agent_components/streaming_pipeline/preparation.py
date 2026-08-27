"""
流式请求预处理阶段
从 streaming.py 解耦：系统事件检测、敏感/云端模式检测、偏好读取、
并行任务处理（生命模拟/感官/行为链/依赖解锁）、情绪注入
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger

# 注意：这里与 streaming.py 引用的是同一个类对象，
# 单测对类属性（如 StreamContextBuilder.detect_sensitive_mode）的 monkeypatch 依然生效
from ..stream_utils import ParallelProcessor, StreamContextBuilder

logger = get_logger("ChatAgent")


@dataclass
class StreamPreparation:
    """预处理阶段产出的全部状态"""
    message_text: str = ""
    is_system_event: bool = False
    is_sensitive_mode: bool = False
    is_cloud: bool = True
    mode: str = "chat"
    wants_long: bool = False
    max_tokens: Optional[int] = None
    soft_reply_char_limit: Optional[int] = 50
    intimacy_level: float = 0.1
    mood_score: float = 0.5
    shyness_score: float = 0.1
    is_sick: bool = False
    immune_damage: float = 0.0
    life_level: Any = 1
    # 预处理期间需要透传给前端的事件（感官触发/行为链/解锁通知）
    pre_events: List[Dict[str, Any]] = field(default_factory=list)
    active_tools: List[str] = field(default_factory=list)


async def prepare_stream_request(
    agent: Any,
    user_id: str,
    message: Any,
    model_hint: Optional[str],
    system_prompt: Optional[str],
    max_tokens: Optional[int],
) -> StreamPreparation:
    """执行流式对话前的全部预处理，返回 StreamPreparation"""
    prep = StreamPreparation()

    # 检测系统事件
    if isinstance(message, list):
        for item in message:
            if item.get("type") == "text":
                prep.message_text += item.get("text", "")
    else:
        prep.message_text = str(message or "")
        prep.is_system_event = prep.message_text.startswith("[SYSTEM_EVENT:PURCHASE]")

    if prep.is_system_event:
        logger.info(f"Detected purchase event: {prep.message_text}")

    # 使用StreamContextBuilder检测敏感模式
    prep.is_sensitive_mode = await StreamContextBuilder.detect_sensitive_mode(
        agent, user_id, prep.message_text, system_prompt
    )

    # 检测云端模式
    from ..context_persona import detect_cloud_mode
    prep.is_cloud = detect_cloud_mode(agent, model_hint)

    # 检测对话模式
    prep.mode = StreamContextBuilder.detect_mode(agent, prep.message_text)
    prep.wants_long = StreamContextBuilder.detect_wants_long(prep.message_text)

    # 只计算一次本轮工具集合，后续 prompt 文本和原生 function schema 共用。
    from ..context_persona import prepare_active_tools
    prep.active_tools = await prepare_active_tools(agent, prep.message_text, model_hint)

    # 获取偏好设置
    pref_length = "normal"
    try:
        from core.managers.preference_manager import get_preference_manager
        pm = get_preference_manager()
        if pm:
            pref_length = pm.preferences.get("response_length", "normal")
    except Exception as e:
        logger.warning(f"Failed to get preferences: {e}")

    # 推断max_tokens
    prep.max_tokens = StreamContextBuilder.infer_max_tokens(
        prep.mode, prep.is_sensitive_mode, prep.is_system_event,
        prep.wants_long, pref_length, max_tokens
    )

    # 推断软性回复限制
    prep.soft_reply_char_limit = StreamContextBuilder.infer_soft_reply_limit(
        prep.mode, prep.wants_long, prep.is_system_event, prep.message_text
    )

    # 获取亲密度
    if getattr(agent, "dependency_manager", None):
        try:
            prep.intimacy_level = float(
                agent.dependency_manager.get_intimacy_level() or prep.intimacy_level
            )
        except Exception:
            pass

    # 使用ParallelProcessor并行处理
    parallel_results = await ParallelProcessor.process_all(
        agent, prep.message_text, prep.intimacy_level
    )

    # 提取生命统计
    (
        prep.mood_score,
        prep.shyness_score,
        prep.is_sick,
        prep.immune_damage,
        prep.life_level,
    ) = ParallelProcessor.extract_life_stats(parallel_results["life_stats"])

    # 处理亲密度上下文
    updated_shyness = await ParallelProcessor.handle_intimacy_context(
        prep.message_text, prep.intimacy_level
    )
    if updated_shyness is not None:
        prep.shyness_score = updated_shyness

    # 更新情感管理器
    try:
        agent.emotion_manager.ingest_life_stats(
            user_id,
            {
                "mood_score": prep.mood_score,
                "shyness_score": prep.shyness_score,
                "immune_damage": prep.immune_damage,
                "is_sick": prep.is_sick,
                "level": prep.life_level,
            },
            intimacy_level=prep.intimacy_level,
        )
    except Exception:
        pass

    # 检测用户文本情绪并更新AI角色情绪（情绪传染）
    try:
        agent.emotion_manager.process_text(user_id, prep.message_text)
    except Exception:
        pass

    # 收集需要透传给前端的事件
    sensory_feedback = parallel_results["sensory_feedback"]
    behavior_chain = parallel_results["behavior_chain"]

    if sensory_feedback:
        prep.pre_events.append({"type": "sensory_trigger", "data": sensory_feedback, "done": False})

    if behavior_chain:
        prep.pre_events.append({"type": "behavior_chain", "data": behavior_chain, "done": False})

    # 处理依赖解锁
    dep_result = parallel_results["dep_result"]
    if dep_result.get("new_unlocks"):
        prep.pre_events.append({
            "type": "notification",
            "data": {
                "title": "解锁新特性",
                "content": f"已解锁: {', '.join(dep_result['new_unlocks'])}",
            },
            "done": False,
        })

    # 记录触发的缺陷
    if parallel_results["triggered_defects"]:
        logger.info(f"触发人格缺陷: {parallel_results['triggered_defects']}")

    return prep
