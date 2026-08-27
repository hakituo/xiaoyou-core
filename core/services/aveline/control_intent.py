import asyncio
import re
from typing import Any, Dict, Optional, Tuple

from config.integrated_config import get_settings
from core.services.aveline.mode_control import handle_natural_mode_control
from core.services.intent.service import classify_intent as core_classify_intent

_GATE_KEYWORDS_RE = re.compile(
    r"(清空|清除|重置|忘掉|忘记|删除|格式化|记忆|历史|上下文|对话|聊天|会话|模型|人设|角色|性格|设定|声音|语音|音色|帮助|菜单|指令|状态|负载|占用|CPU|GPU|显存|内存|latency|仿生|画|生图)",
    re.IGNORECASE,
)
_PURE_CHAT_SHORT_RE = re.compile(
    r"^(你好|在吗|哈喽|哦|嗯|呵呵|哒|哈|嘻嘻|晚安|早安|去睡了|吃饭了|再见|拜拜)$"
)
_HAS_INST_HINT_RE = re.compile(
    r"(换|变|切|看|查|调|显|设|听|说|读|写|选|用|给|帮|把|弄|搞|模型|样子|声音|状态|配置|参数|性能|数据|逻辑|脑子|智商|显存|占用)"
)


async def check_control_intent(
    service: Any, user_input: str, conversation_id: str
) -> Optional[Tuple[str, Dict[str, Any]]]:
    user_input_lower = user_input.lower()
    from core.managers.preference_manager import get_preference_manager

    prefs = get_preference_manager()

    mode_handled = await handle_natural_mode_control(user_input_lower, prefs)
    if mode_handled:
        return mode_handled

    if any(
        x in user_input_lower for x in ["开启主动关怀", "打开主动关怀", "enable active care"]
    ):
        await prefs.set_active_care(True)
        return "主动关怀已开启。", {
            "status": "success",
            "command": "care",
            "enabled": True,
        }

    if any(
        x in user_input_lower
        for x in ["关闭主动关怀", "暂停主动关怀", "disable active care"]
    ):
        await prefs.set_active_care(False)
        return "主动关怀已关闭。", {
            "status": "success",
            "command": "care",
            "enabled": False,
        }

    if any(x in user_input_lower for x in ["忘掉刚才说的", "forget it", "forget this"]):
        return await service._handle_command("/forget", conversation_id)

    if any(
        x in user_input_lower
        for x in [
            "清除记忆",
            "清空记忆",
            "清除历史",
            "清空历史",
            "清除历史记录",
            "清空历史记录",
            "清除聊天记录",
            "清空聊天记录",
            "清除上下文",
            "清空上下文",
            "重置对话",
            "重置聊天",
            "重新开始",
            "clear memory",
            "clear history",
            "reset chat",
        ]
    ):
        return await service._handle_command("/clear", conversation_id)

    return await check_llm_control_intent(service, user_input, conversation_id)


async def check_llm_control_intent(
    service: Any, user_input: str, conversation_id: str
) -> Optional[Tuple[str, Dict[str, Any]]]:
    try:
        t_strip = str(user_input or "").strip()
        if not t_strip:
            return None

        if re.fullmatch(r"\[[^\]]+\]", t_strip):
            return None

        if not _GATE_KEYWORDS_RE.search(t_strip):
            if _PURE_CHAT_SHORT_RE.match(t_strip):
                return None
            if len(t_strip) <= 3:
                return None
            if len(t_strip) > 20 and not _HAS_INST_HINT_RE.search(t_strip):
                return None

        candidates = [
            "CLEAR_MEMORY",
            "CLEAR_LOCAL_MEMORY",
            "SHOW_STATUS",
            "SHOW_HELP",
            "LIST_MODELS",
            "LIST_VOICES",
            "SWITCH_MODEL",
            "SWITCH_MODEL_HINT",
            "SWITCH_PERSONA",
            "TOGGLE_LATENCY",
            "IMAGE_GEN",
            "NONE",
        ]

        result = await core_classify_intent(t_strip, candidates=candidates)
        intent = str(result.get("intent") or "NONE").upper()
        confidence = float(result.get("confidence") or 0.0)
        slots = result.get("slots") or {}

        if intent == "NONE" or confidence < 0.5:
            if _PURE_CHAT_SHORT_RE.match(t_strip):
                return None
            if len(t_strip) > 20 and not _HAS_INST_HINT_RE.search(t_strip):
                return None
            return None

        return await _handle_classified_intent(service, intent, slots, conversation_id)
    except Exception:
        return None


async def _handle_classified_intent(
    service: Any, intent: str, slots: Dict[str, Any], conversation_id: str
) -> Optional[Tuple[str, Dict[str, Any]]]:
    if intent == "CLEAR_MEMORY":
        if service.chat_agent:
            await service.chat_agent.clear_history(conversation_id, mode="all")
        return "已为你清空当前对话的记忆上下文。", {
            "status": "success",
            "command": "clear",
        }

    if intent == "CLEAR_LOCAL_MEMORY":
        if service.chat_agent:
            await service.chat_agent.clear_history(conversation_id, mode="all")
        return "已为你彻底清除所有本地记忆记录。", {
            "status": "success",
            "command": "clear_local",
        }

    if intent == "SHOW_HELP":
        return _build_help_result()

    if intent in ("LIST_MODELS", "LIST_VOICES", "SHOW_STATUS"):
        return (
            "这些功能建议使用网页端的设置/面板入口操作（更直观）。\n"
            "如果你是要切模型/切人设/开关延迟，可以直接用自然语言告诉我。",
            {"status": "success", "command": intent.lower()},
        )

    if intent == "TOGGLE_LATENCY":
        state = str(slots.get("state") or "").strip().lower()
        settings = get_settings()
        if state not in ("on", "off"):
            state = "off" if bool(settings.scheduler.bio_enable_cognitive_delay) else "on"
        settings.scheduler.bio_enable_cognitive_delay = state == "on"
        if settings.scheduler.bio_enable_cognitive_delay:
            return "仿生学认知延迟已开启。", {
                "status": "success",
                "command": "latency",
                "enabled": True,
            }
        return "仿生学认知延迟已关闭。", {
            "status": "success",
            "command": "latency",
            "enabled": False,
        }

    if intent == "SWITCH_PERSONA":
        return await _switch_persona(slots)

    if intent in ("SWITCH_MODEL", "SWITCH_MODEL_HINT"):
        return await _switch_model(slots)

    if intent == "IMAGE_GEN":
        return None

    return None


def _build_help_result() -> Tuple[str, Dict[str, Any]]:
    return (
        "你可以直接说：\n"
        "- 切换到 <模型名>\n"
        "- 换成 <人设名>\n"
        "- 开启/关闭 仿生延迟\n"
        "- 画一张 <描述内容>\n"
        "也支持指令：/latency on|off、/clear、/help",
        {"status": "success", "command": "help"},
    )


async def _switch_persona(slots: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    persona_name = str(slots.get("persona_name") or "").strip()
    if not persona_name:
        return "请告诉我你要切换到哪个人设（也可以说人设文件名）。", {
            "status": "info",
            "command": "persona",
        }
    try:
        from core.character.managers.persona_manager import get_persona_manager

        manager = get_persona_manager()
        personas = manager.list_personas() or []
        persona_name_low = persona_name.lower()
        target_filename = ""
        for p in personas:
            if not isinstance(p, dict):
                continue
            fn = str(p.get("filename") or "").strip()
            nm = str(p.get("name") or "").strip()
            if fn.lower() == persona_name_low or nm.lower() == persona_name_low:
                target_filename = fn
                break
        if not target_filename:
            for p in personas:
                if not isinstance(p, dict):
                    continue
                fn = str(p.get("filename") or "").strip()
                nm = str(p.get("name") or "").strip()
                if persona_name_low and (
                    persona_name_low in fn.lower() or persona_name_low in nm.lower()
                ):
                    target_filename = fn
                    break
        if not target_filename:
            target_filename = persona_name
        success = manager.set_persona(target_filename)
        if not success:
            return "没有找到匹配的人设。可以先在设置里查看人设列表。", {
                "status": "error",
                "command": "persona",
            }
        try:
            from core.character.aveline import AvelineCharacter

            AvelineCharacter().load_config()
        except Exception:
            pass
        return f"人设已切换为: {target_filename}", {
            "status": "success",
            "command": "persona",
            "filename": target_filename,
        }
    except Exception:
        return "切换人设失败。", {"status": "error", "command": "persona"}


async def _switch_model(slots: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    model_name = str(slots.get("model_name") or "").strip()
    if not model_name:
        return (
            "请告诉我你要切换到哪个模型（也可以先在设置里看模型列表）。",
            {"status": "info", "command": "model"},
        )

    try:
        from core.core_engine.model_manager import get_model_manager
        from routers.v1.models import MODEL_OPTIONS

        manager = get_model_manager()
        raw_models = []
        try:
            raw_models.extend(manager.list_models(model_type="llm") or [])
        except Exception:
            raw_models = []
        raw_models.extend(list(MODEL_OPTIONS or []))

        q = model_name.lower().strip()
        best = None
        best_score = -1
        for m in raw_models:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id") or "").strip()
            nm = str(m.get("name") or "").strip()
            mm = str(m.get("model") or "").strip()
            hay = f"{mid} {nm} {mm}".lower()
            if not q or q not in hay:
                continue
            score = 1
            if mid.lower() == q or mm.lower() == q or nm.lower() == q:
                score = 100
            elif (
                mid.lower().startswith(q)
                or mm.lower().startswith(q)
                or nm.lower().startswith(q)
            ):
                score = 50
            if score > best_score:
                best_score = score
                best = m

        provider = "local"
        target_model = model_name
        if isinstance(best, dict):
            provider = str(best.get("provider") or provider).strip() or provider
            target_model = str(
                best.get("id") or best.get("model") or best.get("name") or target_model
            ).strip()
            if (
                provider != "local"
                and isinstance(best.get("model"), str)
                and best.get("model")
            ):
                target_model = str(best.get("model"))

        settings = get_settings()
        settings.model.llm.provider = provider
        if provider == "local":
            from routers.v1.models import MODEL_OPTIONS as _MODEL_OPTIONS

            found_option = next(
                (opt for opt in (_MODEL_OPTIONS or []) if opt.get("id") == target_model),
                None,
            )
            if isinstance(found_option, dict) and found_option.get("path"):
                settings.model.text_path = str(found_option.get("path"))
            else:
                try:
                    model_info = manager._models.get(target_model)
                    if not model_info:
                        for k, v in manager._models.items():
                            if str(k).lower() == target_model.lower():
                                model_info = v
                                break
                    if model_info and getattr(model_info, "model_path", None):
                        settings.model.text_path = str(model_info.model_path)
                    else:
                        if "/" in target_model or "\\" in target_model:
                            settings.model.text_path = target_model
                except Exception:
                    pass
        else:
            settings.model.llm.model = target_model

        from core.llm import get_llm_module

        module = get_llm_module()
        if hasattr(module, "reload"):
            if asyncio.iscoroutinefunction(module.reload):
                await module.reload()
            else:
                module.reload()

        return (
            f"模型已切换为: {target_model} ({provider})",
            {
                "status": "success",
                "command": "model",
                "provider": provider,
                "model": target_model,
            },
        )
    except Exception:
        return "切换模型失败。", {"status": "error", "command": "model"}
