"""MessagePeerTool — 让 LLM 在和主人聊天时，主动给另一个角色发消息。

当七濑 澪和Ling聊天时提到要去找对方、关心对方状态等，
LLM 可以调用此工具触发给对方角色的互聊剧本生成。

调用后不会立即发消息，而是交给 active care 的 generate_peer_script
生成一段自然的对话剧本，再按延迟分发到各自的 QQ。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("MessagePeerTool")


def _get_peer_role_names() -> dict:
    """动态构建 role_id → 中文名 映射(N 角色从 personas 加载)"""
    try:
        from core.services.dual_role.personas import PERSONAS
        return {p.role_id: p.cn_name for p in PERSONAS.values()}
    except Exception:
        # 兜底
        return {"ling": "Ling", "aveline": "七濑 澪"}


class MessagePeerInput(BaseModel):
    peer_role: str = Field(
        description="要发消息给的角色。'ling'（Ling）或 'aveline'（七濑 澪）。"
    )
    topic: str = Field(
        description="想和对方聊的话题，如'关心她吃饭了没'、'约她一起看剧'、'问她作业写完没'。"
    )
    reason: Optional[str] = Field(
        default=None,
        description="为什么要给对方发消息（简要说明，不会发给对方，仅用于决策日志）",
    )


class MessagePeerTool(BaseTool):
    name = "message_peer"
    description = (
        "主动给另一个角色（Ling/七濑 澪）发QQ消息，触发一段自然的对话剧本。"
        "当你觉得应该去找对方聊聊时使用，比如："
        "1. 你提到'我去看看Ling'、'得去找她聊聊'等意图时；"
        "2. 你关心对方的状态（如'她精力归零了，我得去看看'）；"
        "3. 你想约对方做某事（如'叫Ling一起吃饭'）；"
        "4. 你想和对方分享某件事，尤其是主人刚告诉你的事需要让对方知情时——"
        "应通过此工具发起 peer chat 把情报告诉对方，让对方通过你们互聊自然得知，"
        "而不是让对方去直接问主人'你怎么了'。"
        "调用后会生成一段自然的对话剧本，不会直接发你输入的内容。"
        "不要滥用，只在确实需要和对方交流时才调用。"
    )
    short_description = "给Ling/七濑 澪发QQ消息（触发互聊剧本）"
    args_schema = MessagePeerInput
    category = "communication"
    enabled_by_default = True

    async def _run(
        self,
        peer_role: str = "",
        topic: str = "",
        reason: Optional[str] = None,
    ) -> str:
        peer_role = peer_role.strip().lower()
        peer_role_names = _get_peer_role_names()
        if peer_role not in peer_role_names:
            # 列出所有可选角色
            role_list = "、".join(f"{rid}（{name}）" for rid, name in peer_role_names.items())
            return f"无效的角色 '{peer_role}'，可选值：{role_list}。"

        if not topic or not topic.strip():
            return "话题不能为空，请说明想和对方聊什么。"

        topic = topic.strip()[:200]
        peer_name = peer_role_names[peer_role]

        # 从运行时上下文获取当前角色信息
        agent = self._get_ctx("agent")
        user_id = self._get_ctx("user_id") or ""

        # 推断当前角色ID：从 conversation_id 或 persona_filename 中提取
        my_role_id = self._infer_my_role_id(user_id)
        if not my_role_id:
            return f"无法确定当前角色，跳过给{peer_name}发消息。"

        if my_role_id == peer_role:
            return "不能给自己发消息。"

        # 获取 active care executor
        try:
            from core.services.active_care.core.executor import get_active_care_executor
            executor = get_active_care_executor()
        except Exception as e:
            logger.warning(f"获取 executor 失败: {e}")
            return "发送失败：主动关怀系统未就绪。"

        if not executor:
            return "发送失败：主动关怀系统未初始化。"

        # 获取对方角色的 QQ 号
        peer_qq_id = self._get_peer_qq_id(peer_role)
        if not peer_qq_id:
            return f"发送失败：找不到{peer_name}的QQ号。"

        # 获取当前角色的 persona_filename
        persona_filename = self._get_my_persona_filename(my_role_id)

        # 调用 generate_peer_script 生成剧本
        try:
            sent = await executor.generate_peer_script(
                role_id=my_role_id,
                peer_qq_id=peer_qq_id,
                topic=topic,
                persona_filename=persona_filename,
            )
        except Exception as e:
            logger.error(f"message_peer 生成剧本失败: {e}", exc_info=True)
            return f"给{peer_name}发消息失败：剧本生成异常。"

        if sent:
            logger.info(
                "message_peer: %s -> %s, topic='%s', reason='%s'",
                my_role_id, peer_role, topic, reason or "",
            )
            return f"已触发给{peer_name}的消息，话题：{topic}。对话剧本正在生成和发送中。"
        else:
            return f"给{peer_name}发消息失败：剧本生成未成功。"

    def _infer_my_role_id(self, user_id: str) -> str:
        """从 conversation_id 推断当前角色ID(N 角色动态匹配)"""
        uid = str(user_id or "").lower()
        try:
            from core.services.dual_role.personas import PERSONAS
            # 按 role_id 长度降序匹配(避免短名误匹配,如 "ling" 匹配到 "ling_xxx")
            for role_id in sorted(PERSONAS.keys(), key=len, reverse=True):
                if role_id in uid:
                    return role_id
        except Exception:
            pass

        # 从 agent 的 persona_filename 推断
        try:
            agent = self._get_ctx("agent")
            if agent and hasattr(agent, "persona_filename"):
                pf = str(agent.persona_filename or "").lower()
                try:
                    from core.services.dual_role.personas import PERSONAS
                    for role_id in sorted(PERSONAS.keys(), key=len, reverse=True):
                        if role_id in pf:
                            return role_id
                except Exception:
                    pass
        except Exception:
            pass

        # 从全局 persona manager 推断
        try:
            from core.character.managers.persona_manager import get_persona_manager
            current_fn = str(get_persona_manager().get_current_filename() or "").lower()
            try:
                from core.services.dual_role.personas import PERSONAS
                for role_id in sorted(PERSONAS.keys(), key=len, reverse=True):
                    if role_id in current_fn:
                        return role_id
            except Exception:
                pass
        except Exception:
            pass

        return ""

    def _get_peer_qq_id(self, peer_role: str) -> str:
        """获取对方角色的QQ号"""
        try:
            from clients.bots.qq.main import QQAdapter
            active_instances = QQAdapter.get_active_instances()
            for inst in active_instances:
                if str(inst.get("role_id", "")).strip().lower() == peer_role:
                    # peer_qq_id 是对方角色的 QQ 号（即消息要发到的目标 QQ 号）
                    adapter = inst.get("adapter")
                    if adapter:
                        return str(getattr(adapter.cfg, "master_qq_id", "") or "").strip()
        except Exception:
            pass

        # 从 multi_qq_config.json 回退（顶层结构为 {role_id: {...}} 字典）
        try:
            import json
            from pathlib import Path
            config_path = Path("clients/bots/multi_qq_config.json")
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                for role_id, role_cfg in config.items():
                    if not isinstance(role_cfg, dict):
                        continue
                    if str(role_id).strip().lower() == peer_role or str(
                        role_cfg.get("role_id", "")
                    ).strip().lower() == peer_role:
                        return str(role_cfg.get("master_qq_id", "") or "").strip()
        except Exception:
            pass

        return ""

    def _get_my_persona_filename(self, my_role_id: str) -> str:
        """获取当前角色的 persona_filename"""
        try:
            from clients.bots.qq.main import QQAdapter
            active_instances = QQAdapter.get_active_instances()
            for inst in active_instances:
                if str(inst.get("role_id", "")).strip().lower() == my_role_id:
                    return str(inst.get("persona_filename", "") or "").strip()
        except Exception:
            pass

        # N 角色系统:从 personas 查 config_filename 作为默认值
        try:
            from core.services.dual_role.personas import get_persona
            p = get_persona(my_role_id)
            if p:
                return p.config_filename
        except Exception:
            pass
        return ""
