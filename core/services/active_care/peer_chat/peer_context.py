"""双角色互聊上下文拉取器

职责：拉取生成剧本所需的上下文（主人聊天记录 / 互聊历史 / 时间 / 生理状态）。

从 peer_script_generator.py 的 _gather_peer_context 拆分，仅依赖 host.context。
"""

from typing import Any, Dict

from config.debug_config import is_debug_enabled
from core.utils.logger import get_module_logger

# peer_chat 独立日志文件，与 active_care 主流程分离
logger = get_module_logger("PEER_CHAT", "peer_chat.log")


class PeerContextGatherer:
    """双角色互聊上下文拉取器"""

    def __init__(self, context):
        """
        Args:
            context: ActiveCareExecutor.context，用于读取真实聊天历史。
        """
        self._context = context

    async def gather(
        self, role_id: str, peer_role_id: str, cfg: Dict[str, Any]
    ) -> Dict[str, Any]:
        """阶段2：拉取生成剧本所需的上下文（主人聊天记录/互聊历史/时间/生理状态）"""
        from clients.bots.qq.peer_chat import PeerChatManager

        # 分别获取双方各自和主人的真实聊天（信息权限：各自与主人的私聊只归各自知道），
        # 并用知识防火墙剔除含保密信号的私聊行，防止跨关系泄漏进 Peer Chat。
        from core.services.active_care.peer_chat.peer_knowledge import (
            filter_secret_lines,
        )

        master_history_by_role: Dict[str, str] = {}
        recent_master_sections = []
        try:
            from clients.bots.qq.utils import build_persona_conversation_id

            seen_conversation_ids = set()
            for persona_fn, speaker_name, owner_id in (
                (str(cfg.get("role_persona_fn") or ""), str(cfg.get("role_name") or role_id), role_id),
                (str(cfg.get("peer_persona_fn") or ""), str(cfg.get("peer_name") or peer_role_id), peer_role_id),
            ):
                if not persona_fn:
                    continue
                conversation_id = build_persona_conversation_id("shared", persona_fn)
                if not conversation_id or conversation_id in seen_conversation_ids:
                    continue
                seen_conversation_ids.add(conversation_id)
                section = await PeerChatManager.get_recent_master_history(
                    self._context,
                    conversation_id,
                    limit=8,
                    speaker_name=speaker_name,
                )
                if section:
                    # 私聊素材归属对应角色；含保密信号的整行被过滤
                    master_history_by_role[owner_id] = filter_secret_lines(section)
                    recent_master_sections.append(section)
        except Exception as e:
            if is_debug_enabled("peer_script"):
                logger.info(f"获取主人聊天记录失败: {e}")
        # 向后兼容：拼接文本仍保留，供未走知识分桶的旧路径使用
        recent_master_history = "\n\n".join(recent_master_sections)

        # 获取之前的互聊剧本记录
        recent_peer_scripts = ""
        try:
            recent_peer_scripts = await PeerChatManager.get_recent_peer_scripts(
                self._context, role_id, limit=5
            )
        except Exception as e:
            if is_debug_enabled("peer_script"):
                logger.info(f"获取互聊剧本记录失败: {e}")

        # 构建时间字符串
        from core.utils.time_utils import get_current_time
        now_dt = get_current_time()
        time_str = now_dt.strftime('%Y-%m-%d %H:%M')

        # 获取双方生理状态
        bio_state = None
        peer_bio_state = None
        try:
            from core.services.life_simulation import get_life_simulation_service
            life_sim = get_life_simulation_service()
            if life_sim:
                bio_state = life_sim.get_bio_state(role_id)
                peer_bio_state = life_sim.get_bio_state(peer_role_id)
        except Exception:
            pass

        return {
            "recent_master_history": recent_master_history,
            "master_history_by_role": master_history_by_role,
            "recent_peer_scripts": recent_peer_scripts,
            "time_str": time_str,
            "bio_state": bio_state,
            "peer_bio_state": peer_bio_state,
        }