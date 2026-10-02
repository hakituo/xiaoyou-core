"""
人设解析模块
从 executor 中提取，负责人设文件名解析、prompt 加载、语气参考构建
"""

from core.utils.logger import get_logger
from core.character.aveline import AvelineCharacter
from core.character.managers.persona_manager import get_persona_manager
from core.agents.chat_agent_components.persona_system.prompt.data import (
    PersonaPromptLayers,
    get_persona_prompt_layers,
    get_template_data,
    get_persona_name_from_filename,
)
from core.agents.chat_agent_components.persona_system.prompt.dialogue_examples import (
    get_dialogue_examples,
)
from core.services.active_care.shared.text_utils import (
    normalize_persona_token as _normalize_persona_token,
    extract_persona_token as _extract_persona_token,
)

logger = get_logger("ACTIVE_CARE_PERSONA")


class PersonaResolver:
    def __init__(self, storage):
        self.storage = storage

    def resolve_scope(self, conversation_id: str) -> str:
        return self.storage.resolve_scope_from_conversation_id(conversation_id)

    @staticmethod
    def normalize_persona_token(filename: str) -> str:
        return _normalize_persona_token(filename)

    @staticmethod
    def extract_persona_token(conversation_id: str) -> str:
        return _extract_persona_token(conversation_id)

    def resolve_persona_filename(self, conversation_id: str) -> str:
        return PersonaResolver.resolve_persona_filename_static(conversation_id, self.storage)

    def load_persona_prompt(self, conversation_id: str) -> str:
        filename = self.resolve_persona_filename(conversation_id)
        try:
            prompt, _ = get_template_data(persona_filename=filename)
            if prompt:
                return prompt
            pm = get_persona_manager()
            cfg = pm.get_persona_by_filename(filename) or {}
            if isinstance(cfg, dict):
                identity = cfg.get("identity") if isinstance(cfg.get("identity"), dict) else {}
                cn_name = str(identity.get("cn_name") or identity.get("name") or "").strip()
                context = str(identity.get("context") or "").strip()
                if cn_name or context:
                    return f"你是{cn_name or '该角色'}。{context}".strip()
        except Exception as e:
            logger.warning(f"Active Care persona load failed for {filename}: {e}")
        try:
            return AvelineCharacter().get_system_prompt_template()
        except Exception:
            return ""

    def load_persona_prompt_layers(
        self,
        conversation_id: str,
        message: str = "",
    ) -> PersonaPromptLayers:
        """加载与主对话一致的人设 Prompt 分层，旧角色自动兼容。"""
        filename = self.resolve_persona_filename(conversation_id)
        try:
            pm = get_persona_manager()
            persona_data = pm.get_persona_by_filename(filename) or {}
            layers = get_persona_prompt_layers(
                persona_filename=filename,
                message=message,
                persona_data=persona_data if isinstance(persona_data, dict) else {},
                conversation_id=conversation_id,
                update_working_set=False,
            )
            if layers.uses_layered_prompt or layers.static_prompt:
                return layers

            fallback_prompt = self.load_persona_prompt(conversation_id)
            return PersonaPromptLayers(static_prompt=fallback_prompt)
        except Exception as exc:
            logger.warning(
                "Active Care persona layers load failed for %s: %s",
                filename,
                exc,
            )
            return PersonaPromptLayers(
                static_prompt=self.load_persona_prompt(conversation_id)
            )

    def is_runtime_private_mode(self, conversation_id: str) -> bool:
        """读取主人设动态层的私密状态，供主动消息门控复用。"""
        try:
            return self.load_persona_prompt_layers(
                conversation_id,
            ).private_overlay_active
        except Exception:
            return False

    def build_decision_persona_summary(self, conversation_id: str) -> str:
        """为发送决策提供轻量身份投影，避免截取完整 V2 Prompt 的规则前缀。"""
        filename = self.resolve_persona_filename(conversation_id)
        persona_name = get_persona_name_from_filename(filename) or "当前角色"
        scope = str(self.resolve_scope(conversation_id) or "").strip()
        scope_hint = f"（稳定 scope={scope}）" if scope else ""
        return (
            f"当前主动消息角色：{persona_name}{scope_hint}。"
            "本阶段只决定是否发送与消息意图；完整角色表达由生成阶段的 "
            "Persona Prompt V2 约束。"
        )

    def build_tone_reference(
        self,
        conversation_id: str,
        message_for_style: str,
        is_sensitive_mode: bool,
        max_chars: int = 7000,
    ) -> str:
        filename = self.resolve_persona_filename(conversation_id)
        persona_name = get_persona_name_from_filename(filename)

        # 语气参考统一走 dialogue_examples 数据层：有该角色的对话示例数据就注入，
        # 没有就返回空（不注入任何角色硬编码示例）。语气完全交由 Persona 的
        # CHARACTER VOICE 表达，新增角色只需在该数据层补充示例文件，无需改本函数。
        query_text = str(message_for_style or "").strip() or "继续刚才的话题"
        try:
            dialogue_text = get_dialogue_examples(
                agent=None,
                message=query_text,
                mode="chat",
                is_sensitive_mode=is_sensitive_mode,
                is_local_gguf=False,
                allow_sensitive_dialogue_examples=is_sensitive_mode,
                persona_name=persona_name,
            )
            if str(dialogue_text or "").strip():
                trimmed = str(dialogue_text).strip()
                if len(trimmed) > max(200, max_chars):
                    trimmed = trimmed[: max(200, max_chars)]
                return (
                    "\n【参考对话（只学习语气、节奏和用词，不要照抄内容）】\n"
                    + trimmed
                    + "\n"
                )
        except Exception as e:
            logger.warning(f"Active Care tone reference load failed for {filename}: {e}")

        return ""

    @staticmethod
    def is_sensitive_mode(persona_filename: str) -> bool:
        return "sensitive/" in str(persona_filename or "").replace("\\", "/").lower()

    @staticmethod
    def resolve_persona_filename_static(conversation_id: str, storage) -> str:
        try:
            pm = get_persona_manager()
            personas = pm.list_personas()
            token = PersonaResolver.extract_persona_token(conversation_id)
            if token:
                # 优先匹配非 sensitive 人设
                non_sensitive_matches = []
                sensitive_matches = []
                for item in personas:
                    filename = str((item or {}).get("filename") or "").strip()
                    if not filename:
                        continue
                    if PersonaResolver.normalize_persona_token(filename) == token:
                        # 区分 sensitive 和非 sensitive 人设
                        if PersonaResolver.is_sensitive_mode(filename):
                            sensitive_matches.append(filename)
                        else:
                            non_sensitive_matches.append(filename)
                
                # 检查 conversation_id 本身是否暗示敏感模式
                # 如果用户明确使用了 sensitive 人设的 conversation_id，优先返回 sensitive 人设
                cid_lower = str(conversation_id or "").replace("\\", "/").lower()
                explicit_sensitive = "sensitive" in cid_lower or "_love" in cid_lower or "_nsfw" in cid_lower
                
                if explicit_sensitive and sensitive_matches:
                    return sensitive_matches[0]
                # 优先返回非 sensitive 人设
                if non_sensitive_matches:
                    return non_sensitive_matches[0]
                if sensitive_matches:
                    return sensitive_matches[0]

                # 文件名 token 与稳定 role_id 不一定完全相同（例如 core_ye → ye）。
                # 复用角色注册表恢复权威配置，新增角色无需继续扩充本地 if 列表。
                from core.services.dual_role.personas import get_persona

                profile = get_persona(token.removeprefix("core_"))
                if profile:
                    return profile.config_filename

                # 向后兼容：旧双角色 token 仍保留原回退。
                if token in {"core_ling", "ling"}:
                    return "core_ling.json"
                if token in {"core_aveline", "aveline"}:
                    return "core_aveline.json"
            scope = str(
                storage.resolve_scope_from_conversation_id(conversation_id) or "aveline"
            ).strip().lower()
            from core.services.dual_role.personas import get_persona

            profile = get_persona(scope)
            if profile:
                return profile.config_filename
            if scope == "ling":
                return "core_ling.json"
            return "core_aveline.json"
        except Exception:
            pass
        token = PersonaResolver.extract_persona_token(conversation_id)
        if token in {"core_ling", "ling"}:
            return "core_ling.json"
        return "core_aveline.json"
