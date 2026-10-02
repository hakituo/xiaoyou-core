"""
双角色互聊后处理 hooks 模块（从 peer_script_generator.py 拆分）

职责：剧本分发成功后的后处理副作用，包含：
- 写普通日记
- 触发代码巡检（auto_heal）
- 保存剧本记录到 peer_{role_id} conversation
- 若末句 mention_user，触发主动关怀通知主人
- 巡检报告写入记忆
"""


from core.utils.logger import get_module_logger
from typing import Any, Dict

from config.debug_config import is_debug_enabled

# peer_chat 独立日志文件，与 active_care 主流程分离
logger = get_module_logger("PEER_CHAT", "peer_chat.log")


async def run_peer_post_hooks(
    *,
    script: list,
    role_id: str,
    peer_role_id: str,
    cfg: Dict[str, Any],
    should_notify_user: bool,
    notify_content: str,
    host,
) -> None:
    """剧本分发成功后的后处理 hooks

    Args:
        script: 剧本列表
        role_id: 发起方角色ID
        peer_role_id: 对方角色ID
        cfg: 配置字典
        should_notify_user: 是否需要通知主人
        notify_content: 通知内容
        host: ActiveCareExecutor 实例，提供 write_diary_entry/trigger_message 回调
    """
    role_name = cfg["role_name"]
    peer_name = cfg["peer_name"]
    role_persona_fn = cfg["role_persona_fn"]

    # 写普通日记（委托给宿主的 write_diary_entry）
    summary = script[0].get("content", "") if script else ""
    await host.write_diary_entry(
        "peer_chat",
        f"和{peer_name}聊了{len(script)}轮",
        thought=f"主动找{peer_name}聊天: {summary[:30]}",
    )

    # 触发代码巡检
    await _maybe_trigger_peer_chat_patrol(role_id, role_name)

    # 保存剧本记录到 peer_{role_id} conversation
    try:
        from core.core_engine.service_singletons import get_aveline_service
        peer_conv_id = f"peer_{role_id}"
        aveline_service = get_aveline_service()
        for line in script:
            line_role = line.get("role", "")
            line_content = line.get("content", "")
            if line_content:
                role_label = role_name if line_role == role_id else peer_name
                await aveline_service.append_proactive_message(
                    conversation_id=peer_conv_id,
                    content=f"{role_label}: {line_content}",
                    thought="peer_chat剧本记录",
                )
        logger.info("Active Care: 已保存%d条剧本记录到 %s", len(script), peer_conv_id)
    except Exception as e:
        logger.warning(f"Active Care: 保存剧本记录失败: {e}")

    # 若提及主人，触发主动关怀（委托给宿主的 trigger_message）
    if should_notify_user:
        try:
            logger.info(
                "Active Care: peer_chat剧本完成，提及主人，触发主动关怀 notify_content=%s",
                notify_content[:50],
            )
            try:
                from core.services.active_care.peer_chat.peer_chat_metrics import get_peer_chat_metrics
                get_peer_chat_metrics().incr("mention_triggered")
            except Exception:
                pass
            await host.trigger_message(
                sys_prompt_type="share_peer_chat",
                user_input_mock=f"[PEER_CHAT_CONTEXT]: 刚才和{peer_name}聊了{len(script)}轮，最后{peer_name}提到了主人：「{notify_content}」",
                thought=f"和{peer_name}的对话中提到了主人，需要主动联系主人",
                specific_instruction=f"你刚刚和{peer_name}聊完天，{peer_name}提到了主人（Master）。请自然地找主人聊聊这个话题，不要暴露你在和{peer_name}私聊的细节。",
                persona_filename=role_persona_fn,
            )
        except Exception as e:
            logger.warning(f"Active Care: peer_chat触发主动关怀失败: {e}")


async def _maybe_trigger_peer_chat_patrol(
    role_id: str, role_name: str
) -> None:
    """互聊完成后触发代码巡检（从 DualRoleCoordinator 合并）"""
    try:
        from core.services.auto_heal.heal_service import get_auto_heal_service
        heal_svc = get_auto_heal_service()
        if not heal_svc:
            return
        # 获取健康报告
        stats = heal_svc.get_stats()
        patches_by_status = stats.get("patches_by_status", {})
        error_stats = stats.get("error_stats", {})
        pending = patches_by_status.get("awaiting_approval", 0)
        total_anomalies = error_stats.get("total_anomalies", 0)
        if total_anomalies == 0 and pending == 0:
            return  # 无异常，不触发巡检
        # 构建角色上下文
        persona_context = build_patrol_persona(role_id, role_name)
        logger.info("Active Care: 互聊后巡检 %s 开始 (异常=%d, 待审批=%d)", role_name, total_anomalies, pending)
        results = await heal_svc.trigger_check(persona_context=persona_context)
        if results:
            logger.info("Active Care: 互聊后巡检完成: %s 发现 %d 个异常", role_name, len(results))
            # 写入巡检报告到记忆
            await _write_patrol_report_to_memory(role_name, results)
        else:
            logger.info("Active Care: 互聊后巡检完成: %s 未发现新异常", role_name)
    except Exception as e:
        if is_debug_enabled("peer_script"):
            logger.info("Active Care: 互聊后巡检触发失败: %s", e)


def build_patrol_persona(role_id: str, role_name: str) -> str:
    """构建巡检角色上下文"""
    try:
        from core.character.managers.persona_manager import get_persona_manager
        pm = get_persona_manager()
        persona_filename = "core_ling.json" if role_id == "ling" else "core_aveline.json"
        cfg = pm.load_persona_config(persona_filename)
        if not cfg:
            return f"你的名字是{role_name}。你现在在帮主人做代码巡检和审阅工作。"
        parts = []
        system_prompt = cfg.get("system_prompt") or ""
        if system_prompt:
            parts.append(system_prompt.strip())
        identity = cfg.get("identity") or {}
        name = identity.get("cn_name") or identity.get("name") or role_name
        context = identity.get("context") or ""
        traits = identity.get("personality_traits") or []
        style = cfg.get("language_style") or {}
        syntax = style.get("syntax_constraints") or []
        if not system_prompt and context:
            parts.append(f"你的名字是{name}。{context}")
        if traits:
            parts.append(f"你的性格特征：{'、'.join(traits[:5])}。")
        if syntax:
            parts.append(f"你的说话风格：{'、'.join(syntax[:3])}。")
        parts.append("你现在在帮主人做代码巡检和审阅工作。")
        return "\n".join(parts)
    except Exception:
        return f"你的名字是{role_name}。你现在在帮主人做代码巡检和审阅工作。"


async def _write_patrol_report_to_memory(assigned_name: str, results: list) -> None:
    """将巡检报告写入记忆"""
    items = []
    for r in results[:5]:
        sev = str(r.get("severity") or "unknown")
        title = str(r.get("title") or "未知异常")
        fixable = "可自动修复" if r.get("auto_fixable") else "需人工处理"
        items.append(f"- [{sev}] {title}（{fixable}）")
    summary = (
        f"{assigned_name}做了一次代码巡检，发现 {len(results)} 个异常：\n"
        + "\n".join(items)
    )
    try:
        from memory.weighted_memory_manager import get_weighted_memory_manager
        mm = get_weighted_memory_manager("default")
        if mm:
            mm.add_memory(
                content=summary,
                role="system",
                is_important=False,
                source="patrol_report",
                category="auto_heal",
                scopes=["local"],
                metadata={
                    "type": "patrol_report",
                    "patrol_by": assigned_name,
                    "anomaly_count": len(results),
                    "hidden": False,
                },
            )
            logger.info("Active Care: 巡检报告已写入记忆: %s", assigned_name)
    except Exception as e:
        if is_debug_enabled("peer_script"):
            logger.info("Active Care: 巡检报告写入记忆失败: %s", e)
