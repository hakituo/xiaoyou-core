"""
双角色互聊剧本分发模块（从 peer_script_generator.py 拆分）

职责：将生成的剧本逐条分发到各自 QQ，包含：
- QQ 路由（根据 line_role 确定目标 conversation_id 和 QQ 号）
- WebSocket 广播（通过 AvelineService.dispatch_proactive_message）
- 消息间延迟（PeerChatManager.calc_message_delay）
- mention_user 检测（末句提及主人时标记 should_notify_user）
"""

from core.utils.logger import get_module_logger
import asyncio

from typing import Any, Dict, Tuple

from config.debug_config import is_debug_enabled

# peer_chat 独立日志文件，与 active_care 主流程分离
logger = get_module_logger("PEER_CHAT", "peer_chat.log")


async def dispatch_script(
    *,
    script: list,
    role_id: str,
    peer_role_id: str,
    cfg: Dict[str, Any],
) -> Tuple[bool, bool, str]:
    """分发剧本到各自QQ（逐条 dispatch + delay）

    Args:
        script: 剧本列表，每项含 role/content/mention_user
        role_id: 发起方角色ID
        peer_role_id: 对方角色ID
        cfg: 配置字典（master_qq_id/role_persona_fn/peer_persona_fn 等）

    Returns:
        (sent_any, should_notify_user, notify_content)
    """
    from clients.bots.qq.peer_chat import PeerChatManager
    from core.core_engine.service_singletons import get_aveline_service
    from clients.bots.qq.utils import build_persona_conversation_id

    aveline_service = get_aveline_service()
    if not aveline_service:
        logger.warning("Active Care: peer_chat分发失败，AvelineService不可用")
        return False, False, ""

    master_qq_id = cfg["master_qq_id"]
    role_persona_fn = cfg["role_persona_fn"]
    peer_persona_fn = cfg["peer_persona_fn"]
    role_name = cfg["role_name"]
    peer_name = cfg["peer_name"]
    role_qq_id = cfg["role_qq_id"]
    peer_role_qq_id = cfg["peer_role_qq_id"]

    base_cid = f"private_{master_qq_id}"
    role_cid = build_persona_conversation_id(base_cid, role_persona_fn)
    peer_cid = build_persona_conversation_id(base_cid, peer_persona_fn)

    logger.info("Active Care: peer_chat分发目标 role_cid=%s, peer_cid=%s, role_qq=%s, peer_qq=%s", role_cid, peer_cid, role_qq_id, peer_role_qq_id)

    sent_any = False
    should_notify_user = False
    notify_content = ""

    for i, line in enumerate(script):
        line_role = line.get("role", "")
        content = line.get("content", "")
        mention_user = line.get("mention_user", False)

        if not content:
            continue

        # 记录是否有提及主人的行
        if mention_user and i == len(script) - 1:
            should_notify_user = True
            notify_content = content

        # 剧本消息：content 保持纯台词（QQ 显示正常，不浪费 token）
        # 说话者信息通过 extra_payload 元数据传递，不塞进文本
        speaker_name = role_name if line_role == role_id else peer_name
        script_content = content

        # 确定目标conversation_id和target_qq_id
        # 路由只看 line_role，mention_user 不影响路由
        if line_role == role_id:
            target_cid = role_cid
            target_qq = peer_role_qq_id
            logger.info(f"剧本分发 [{i+1}/{len(script)}] -> {peer_name}: {content[:30]}...")
        elif line_role == peer_role_id:
            target_cid = peer_cid
            target_qq = role_qq_id
            logger.info(f"剧本分发 [{i+1}/{len(script)}] -> {role_name}: {content[:30]}...")
        else:
            continue

        # 通过WebSocket广播发送
        # extra_payload 携带 peer_speaker（说话者），存储时进 metadata 而非 content
        # role_id 用于存储时路由到独立的 peer_{role_id} conversation
        extra = {
            "target_qq_id": target_qq,
            "is_peer_script": True,
            "message_type": "peer_script",
            "peer_speaker": speaker_name,
            "role_id": line_role,
        }
        result = await aveline_service.dispatch_proactive_message(
            target_conversation_id=target_cid,
            content=script_content,
            thought="双角色互聊剧本",
            message_type="text",
            client_type="qq",
            # 传入主人原始 cid 作为广播目标，确保消息发到主人的所有 QQ 角色连接
            # （target_cid 是 shared__persona__xxx，广播 shared 会因无该用户而进离线队列）
            original_primary_conversation_id=base_cid,
            extra_payload=extra,
        )
        if result.get("delivered"):
            sent_any = True

        # 消息间延迟（最后一条不需要延迟）
        if i < len(script) - 1:
            delay = PeerChatManager.calc_message_delay(content)
            if is_debug_enabled("peer_script"):
                logger.info(f"剧本延迟: {delay:.1f}s")
            await asyncio.sleep(delay)

    return sent_any, should_notify_user, notify_content
