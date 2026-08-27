"""
QQ适配器 - 双角色互聊管理
管理 PeerChat 相关的逻辑，包括角色配置、剧本生成、剧本分发
"""

import json
import asyncio
import random
import time
from typing import Any, Dict, List

from core.utils.logger import get_module_logger

# peer_chat 独立日志文件，与 active_care 主流程分离
logger = get_module_logger("PEER_CHAT", "peer_chat.log")


class PeerChatManager:
    """双角色互聊管理器"""

    # 角色配置 —— 从 dual_role.personas 统一权威源加载
    # （保持属性名 PEER_PROFILES 不变，向后兼容；禁止在此重新硬编码角色名/性格）
    from core.services.dual_role.personas import get_peer_profiles as _get_peer_profiles
    PEER_PROFILES = _get_peer_profiles()

    @staticmethod
    def build_sender_identity_context(
        *,
        role_id: str,
        is_master: bool,
        is_peer_bot: bool,
        peer_qq_id: str = "",
    ) -> dict[str, str]:
        """构建发送者身份上下文（用于普通消息回复时）"""
        role_id = str(role_id or "").strip().lower()
        if is_master:
            return {"sender_identity": "现在跟你说话的是主人Master"}
        if is_peer_bot:
            if role_id == "aveline":
                peer_name = "Ling"
            elif role_id == "ling":
                peer_name = "七濑 澪"
            else:
                peer_name = "对方角色"
            return {"sender_identity": f"现在跟你说话的是{peer_name}，不是主人Master"}
        return {}

    @staticmethod
    def build_peer_role_context(role_id: str, role_name: str) -> dict[str, str]:
        """构建双角色互聊的完整角色上下文"""
        role_id = str(role_id or "").strip().lower()
        role_name = str(role_name or role_id or "当前角色").strip()
        my_profile = PeerChatManager.PEER_PROFILES.get(role_id)
        if role_id == "aveline":
            sender_role_id = "ling"
        elif role_id == "ling":
            sender_role_id = "aveline"
        else:
            sender_role_id = "peer"
        peer_profile = PeerChatManager.PEER_PROFILES.get(sender_role_id)
        if not peer_profile or not my_profile:
            sender_role_name = peer_profile.get("role_name", "对方角色") if peer_profile else "对方角色"
            return {
                "sender_role_id": sender_role_id,
                "sender_role_name": sender_role_name,
                "recipient_role_id": role_id,
                "recipient_role_name": role_name,
            }
        result = {
            "sender_role_id": peer_profile["role_id"],
            "sender_role_name": peer_profile["role_name"],
            "sender_personality": peer_profile["personality"],
            "sender_speaking_style": peer_profile["speaking_style"],
            "sender_relationship": peer_profile["relationship_to_peer"],
            "recipient_role_id": role_id,
            "recipient_role_name": role_name,
            "recipient_personality": my_profile["personality"],
            "recipient_speaking_style": my_profile["speaking_style"],
        }
        return result

    @staticmethod
    def parse_script(raw: str) -> List[Dict[str, Any]]:
        """解析LLM输出的剧本JSON

        Returns:
            解析后的剧本列表，每项包含 role, content, mention_user
        """
        raw = str(raw or "").strip()
        if not raw:
            return []

        # 尝试提取JSON块（支持对象和数组格式）
        import re
        json_match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', raw)
        if json_match:
            raw = json_match.group(0)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"剧本JSON解析失败: {raw[:100]}")
            return []

        if isinstance(data, dict):
            script = data.get("script", [])
        elif isinstance(data, list):
            script = data
        else:
            return []

        if not isinstance(script, list):
            return []

        result = []
        for item in script:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            mention_user = bool(item.get("mention_user", False))
            if role and content:
                result.append({
                    "role": role,
                    "content": content,
                    "mention_user": mention_user,
                })
        return result

    @staticmethod
    def calc_message_delay(content: str) -> float:
        """根据消息内容计算延迟时间（复用现有延迟逻辑）

        简化版：字数 * 0.25秒 + 随机因子
        """
        char_count = len(str(content or ""))
        base_delay = max(0.5, char_count * 0.25)
        # 随机因子 0.7-1.5
        final_delay = base_delay * random.uniform(0.7, 1.5)
        # 短文本额外放大
        if char_count < 10:
            final_delay = max(0.5, final_delay * 1.2)
        # 限制范围
        final_delay = min(7.5, max(0.5, final_delay))
        return final_delay

    @staticmethod
    async def distribute_script(
        script: List[Dict[str, Any]],
        *,
        role_id: str,
        adapter,
        master_qq_id: str,
        broadcast_to_websocket: bool = True,
    ) -> bool:
        """分发剧本到各自QQ

        Args:
            script: 解析后的剧本列表
            role_id: 发起者role_id
            adapter: QQAdapter实例
            master_qq_id: 主人QQ号
            broadcast_to_websocket: 是否广播到WebSocket（供安卓端等客户端使用）
        """
        if not script or not adapter:
            return False

        # N 角色系统:从 personas 获取 peer_role_id 和角色名
        from core.services.dual_role.personas import get_peer_role_id, get_persona
        peer_role_id = get_peer_role_id(role_id)
        if not peer_role_id:
            logger.warning("剧本分发失败: role=%s 无 peer 角色", role_id)
            return False

        # 动态构建 role_name_map(从 personas 加载)
        def _get_role_name(rid: str) -> str:
            p = get_persona(rid)
            return p.cn_name if p else rid

        role_name_map = {
            role_id: _get_role_name(role_id),
            peer_role_id: _get_role_name(peer_role_id),
        }

        # 获取两个角色的QQ号
        role_qq_id = str(getattr(adapter.cfg, "qq_id", "") or "").strip()
        peer_qq_id = str(getattr(adapter.cfg, "peer_qq_id", "") or "").strip()

        if not role_qq_id or not peer_qq_id:
            logger.warning("剧本分发失败: 缺少角色QQ号")
            return False

        # 生成剧本ID
        script_id = f"script_{int(time.time() * 1000)}"

        # 广播剧本开始消息
        if broadcast_to_websocket:
            await PeerChatManager._broadcast_websocket_message({
                "type": "peer_chat_script_start",
                "script_id": script_id,
                "topic": "",  # 可以从外部传入
                "participants": [role_name_map.get(role_id, role_id), role_name_map.get(peer_role_id, peer_role_id)],
                "total_rounds": len(script),
            })

        try:
            for i, line in enumerate(script):
                line_role = line.get("role", "")
                content = line.get("content", "")
                mention_user = line.get("mention_user", False)

                if not content:
                    continue

                # 确定发送目标
                if mention_user and i == len(script) - 1:
                    # 最后一条且提及用户，发给主人
                    target_session = f"private_{master_qq_id}"
                    logger.info(f"剧本分发 [{i+1}/{len(script)}] -> 主人: {content[:30]}...")
                elif line_role == role_id:
                    # 发起者的消息，用发起者的QQ号发给对方
                    target_session = f"peer_{peer_qq_id}"
                    logger.info(f"剧本分发 [{i+1}/{len(script)}] -> {peer_role_id}: {content[:30]}...")
                elif line_role == peer_role_id:
                    # 对方的消息，用对方的QQ号发给发起者
                    target_session = f"peer_{role_qq_id}"
                    logger.info(f"剧本分发 [{i+1}/{len(script)}] -> {role_id}: {content[:30]}...")
                else:
                    continue

                # 广播单条消息到WebSocket
                if broadcast_to_websocket:
                    await PeerChatManager._broadcast_websocket_message({
                        "type": "peer_chat_message",
                        "script_id": script_id,
                        "role": line_role,
                        "role_name": role_name_map.get(line_role, line_role),
                        "text": content,
                        "emotion": line.get("emotion"),
                        "round_index": i,
                        "timestamp": time.time(),
                    })

                # 发送消息
                await adapter.send_to_napcat(target_session, content)

                # 消息间延迟（最后一条不需要延迟）
                if i < len(script) - 1:
                    delay = PeerChatManager.calc_message_delay(content)
                    logger.debug(f"剧本延迟: {delay:.1f}s")
                    await asyncio.sleep(delay)

            # 广播剧本结束消息
            if broadcast_to_websocket:
                last_mention = script[-1].get("mention_user", False) if script else False
                await PeerChatManager._broadcast_websocket_message({
                    "type": "peer_chat_script_end",
                    "script_id": script_id,
                    "summary": f"完成了{len(script)}轮对话",
                    "mentioned_user": last_mention,
                })

            return True

        except Exception as e:
            logger.error(f"剧本分发异常: {e}", exc_info=True)
            return False

    @staticmethod
    async def _broadcast_websocket_message(message: Dict[str, Any]) -> None:
        """广播消息到WebSocket（供安卓端等客户端使用）"""
        try:
            from core.interfaces.websocket.websocket_manager import get_ws_manager
            ws_manager = get_ws_manager()
            if ws_manager:
                await ws_manager.broadcast(message)
                logger.debug(f"WebSocket广播: {message.get('type')}")
        except Exception as e:
            logger.debug(f"WebSocket广播失败: {e}")

    @staticmethod
    async def get_recent_master_history(
        context,
        conversation_id: str,
        limit: int = 10,
        speaker_name: str = "我",
    ) -> str:
        """获取和主人的最近聊天记录（格式化为文本）"""
        try:
            history = await context.get_latest_history_for_conversation(
                conversation_id, limit=max(limit * 3, 20)
            )
            if not history:
                return ""

            lines = ["【和主人的最近聊天】"]
            selected = []
            for msg in history:
                role = str(msg.get("role", "")).strip().lower()
                content = str(msg.get("content", "")).strip()
                if not content:
                    continue
                metadata = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
                source = str(metadata.get("source") or msg.get("source") or "").lower()
                if source == "active_care" or content.startswith("（心想："):
                    continue
                selected.append(msg)

            for msg in selected[-limit:]:
                role = str(msg.get("role", "")).strip().lower()
                content = str(msg.get("content", "")).strip()
                if len(content) > 100:
                    content = content[:100] + "..."
                role_text = "主人" if role == "user" else speaker_name
                lines.append(f"- {role_text}: {content}")
            return "\n".join(lines) if len(lines) > 1 else ""
        except Exception as e:
            logger.debug(f"获取主人聊天记录失败: {e}")
            return ""

    @staticmethod
    async def get_recent_peer_scripts(
        context,
        role_id: str,
        limit: int = 5,
    ) -> str:
        """获取之前的互聊剧本记录（格式化为文本）"""
        try:
            # 互聊记录存在 peer_{role_id} 的conversation中
            peer_conversation_id = f"peer_{role_id}"
            history = await context.get_latest_history_for_conversation(
                peer_conversation_id, limit=limit * 4  # 每个剧本可能有多条消息
            )
            if not history:
                return ""

            lines = ["【之前的互聊记录】"]
            for msg in history[-20:]:
                role = str(msg.get("role", "")).strip().lower()
                content = str(msg.get("content", "")).strip()
                if not content:
                    continue
                if len(content) > 80:
                    content = content[:80] + "..."
                # 从role中提取角色名
                if "aveline" in role:
                    role_text = "七濑 澪"
                elif "ling" in role:
                    role_text = "Ling"
                else:
                    role_text = role
                lines.append(f"- {role_text}: {content}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"获取互聊剧本记录失败: {e}")
            return ""

    @staticmethod
    def detect_peer_mention(text: str, role_id: str) -> str:
        """检测消息中是否提及对方角色

        Args:
            text: 用户消息内容
            role_id: 当前角色ID（aveline或ling）

        Returns:
            如果提及对方，返回对方的role_id；否则返回空字符串
        """
        text = str(text or "").strip()
        if not text:
            return ""

        # N 角色系统:从 personas 获取 peer 角色和关键词
        from core.services.dual_role.personas import get_peer_role_id, get_persona
        peer_role_id = get_peer_role_id(role_id)
        if not peer_role_id:
            return ""

        # 从 personas 加载 peer 的中文名 + 别名作为关键词
        peer_persona = get_persona(peer_role_id)
        if not peer_persona:
            return ""
        peer_keywords = [peer_persona.cn_name]
        # 去掉中文名里的空格作为变体(如"七濑 澪" → "七濑澪")
        no_space_name = peer_persona.cn_name.replace(" ", "")
        if no_space_name != peer_persona.cn_name:
            peer_keywords.append(no_space_name)
        # 加上 personas 里定义的别名
        for alias in (peer_persona.aliases or ()):
            peer_keywords.append(str(alias))

        # 检查是否提及对方
        for keyword in peer_keywords:
            if keyword and keyword in text:
                logger.info(f"检测到提及对方: {keyword} (role_id={role_id})")
                return peer_role_id

        return ""

    @staticmethod
    async def trigger_peer_mention(
        *,
        role_id: str,
        adapter,
        master_qq_id: str,
        context,
        topic: str = "",
    ) -> bool:
        """当用户提及对方时，触发给对方发消息

        Args:
            role_id: 当前角色ID（aveline或ling）
            adapter: QQAdapter实例
            master_qq_id: 主人QQ号
            context: Active Care上下文
            topic: 话题（可选）
        """
        try:
            # N 角色系统:从 personas 获取 peer 角色和名字
            from core.services.dual_role.personas import get_peer_role_id, get_persona
            peer_role_id = get_peer_role_id(role_id)
            if not peer_role_id:
                logger.warning(f"提及对方触发失败: role={role_id} 无 peer 角色")
                return False
            peer_persona = get_persona(peer_role_id)
            peer_name = peer_persona.cn_name if peer_persona else peer_role_id

            # 获取对方的QQ号
            from clients.bots.qq.main import QQAdapter
            active_instances = QQAdapter.get_active_instances()
            peer_adapter = None
            for inst in active_instances:
                if str(inst.get("role_id", "")).strip().lower() == peer_role_id:
                    peer_adapter = inst.get("adapter")
                    break

            if not peer_adapter:
                logger.warning(f"提及对方触发失败: 找不到{peer_role_id}的adapter")
                return False

            peer_qq_id = str(getattr(peer_adapter.cfg, "peer_qq_id", "") or "").strip()
            if not peer_qq_id:
                logger.warning(f"提及对方触发失败: {peer_role_id}的peer_qq_id为空")
                return False

            # 生成剧本
            from core.services.active_care.core.executor import get_active_care_executor
            executor = get_active_care_executor()
            if not executor:
                logger.warning("提及对方触发失败: executor未初始化")
                return False

            # 使用executor生成剧本
            sent = await executor.generate_peer_script(
                role_id=peer_role_id,
                peer_qq_id=peer_qq_id,
                topic=topic or "主人提到你了，来看看",
            )

            if sent:
                logger.info(f"提及对方触发成功: {role_id} -> {peer_name}")

            return sent

        except Exception as e:
            logger.error(f"提及对方触发异常: {e}", exc_info=True)
            return False
