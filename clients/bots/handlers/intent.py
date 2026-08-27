import re
import json
from typing import Optional, Dict, Any
from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.settings import LLM_INTENT_THRESHOLD

class IntentHandler(BaseHandler):
    """
    Handles intent classification (local/LLM) and intent execution routing.
    """
    
    async def classify_intent(self, text: str, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            if not text:
                return None

            t_strip = str(text).strip()
            
            # 1. 快速排除逻辑
            # 如果消息过短（可能是语气词、打招呼），直接跳过识别
            if len(t_strip) <= 2:
                return None

            # 如果文本只是一个表情标签（如 [微笑]），不进行意图路由
            if hasattr(self.adapter, 'face_injector'):
                if re.fullmatch(r"\[[^\]]+\]", t_strip):
                    label = t_strip[1:-1]
                    if label in self.adapter.face_injector._label_to_id:
                        return None

            # 2. 闲聊特征快速拦截（在关键词匹配之前先排除明显的闲聊）
            # [Fix] 防止"不想再被烦了"、"梦里别烦"等纯情感表达被误判为命令
            _chat_patterns = [
                r"^(哈哈|嘿嘿|嗯嗯|哦哦|啊啊|哎|唉|卧槽|草|靠|啧)",  # 语气词/感叹词开头
                r"(嘛呢|咋样|怎么样|好不好|对不对|是不是|行不行)$",   # 疑问/确认语气结尾
                r"(感觉|觉得|好像|可能|大概|应该|似乎).{0,6}$",        # 不确定表达（短句）
                r"^.{0,6}(吗|呢|吧|呀|啦|呗|喔|诶)$",                 # 短句+语气助词
                r"(烦|讨厌|无聊|难受|不开心).{0,4}$",                  # 纯情绪宣泄
            ]
            if any(re.search(p, t_strip, re.IGNORECASE) for p in _chat_patterns):
                return None

            # 3. 关键词初筛（收紧为完整语义单元，避免单字/单词误触发）
            # [Optimization] 从宽松匹配改为要求"动词+对象"成对出现
            cmd_keywords = r"""
                (?:
                    (?:切换|换成|改用|切到|切成)\s*(?:模型|人设|性格|角色) |
                    (?:开启|关闭|打开|禁用|启用|退出|进入)\s*(?:调试|学习|私密|隐私|回复)\s*模式 |
                    /(?:help|帮助|模型|清除|清空|重置|clear) |
                    (?:系统状态|查看状态|模块介绍|模块文档|模块说明) |
                    (?:重置|清空|清除|删除)\s*(?:记忆|本地记忆|缓存) |
                    (?:画一张?|生图|生成图片) |
                    (?:latency|延迟|debug)\s*(?:开关|模式|开启|关闭)? |
                    (?:语音|音色|声音)\s*(?:切换|换成|列表|参考|回复|说|发) |
                    (?:不要|不用|别|关闭|关掉|停止)\s*(?:发|用)?\s*(?:语音|声音) |
                    (?:改成|换成|切成)\s*文字(?:回复)?
                )
            """
            if not re.search(cmd_keywords, t_strip, re.IGNORECASE):
                # logger.debug(f"[{session_id}] Intent pre-filter: No keywords found, skipping LLM classifier.")
                return None
            
            payload = {
                "text": t_strip,
                "candidates": [
                    "CLEAR_MEMORY", "CLEAR_LOCAL_MEMORY", "SHOW_STATUS", "SHOW_HELP", "SHOW_MODULE_DOC",
                    "LIST_MODELS", "LIST_VOICES", "SWITCH_MODEL", "SWITCH_MODEL_HINT",
                    "SWITCH_PERSONA", "TOGGLE_LATENCY", "TOGGLE_REPLY_MODE", "TOGGLE_DEBUG_MODE",
                    "TOGGLE_STUDY_MODE", "TOGGLE_PRIVACY_MODE", "DISABLE_VOICE_REPLY", "SEND_VOICE", "NONE",
                ],
                "max_tokens": 64, # 缩短 token 长度以加速
                "temperature": 0.0,
            }
            
            # 3. 带超时的 API 请求
            status, data = await self.adapter._api_request(
                "POST",
                "/api/v1/context/intent/classify",
                json_body=payload,
                timeout_seconds=2.5, # 严格限时，防止拖累主循环
            )

            if status != 200 or not isinstance(data, dict):
                return None

            if data.get("status") != "success":
                return None

            intent = str(data.get("intent") or "").strip().upper()
            try:
                conf = float(data.get("confidence") or 0.0)
            except Exception:
                conf = 0.0

            if not intent or intent == "NONE":
                return None

            if conf < float(LLM_INTENT_THRESHOLD):
                return None

            slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
            return {"intent": intent, "confidence": conf, "slots": slots}
        except Exception:
            return None

    async def handle_semantic_intent(self, session_id: str, user_id: str, intent: Any, text: str) -> bool:
        """Executes logic based on recognized intent."""
        slots = {}
        intent_name = str(intent or "").strip().upper()
        if isinstance(intent, dict):
            intent_name = str(intent.get("intent") or "").strip().upper()
            slots_obj = intent.get("slots")
            if isinstance(slots_obj, dict):
                slots = slots_obj

        # 4. 二次参数验证：对需要具体参数的意图进行严格校验
        # [Fix] 防止BERT识别出意图但缺少必要参数时仍执行命令
        _PARAM_REQUIRED_INTENTS = {
            "SWITCH_MODEL": ["model_name"],
            "SWITCH_PERSONA": ["persona_name"],
            "TOGGLE_LATENCY": ["state"],
        }
        if intent_name in _PARAM_REQUIRED_INTENTS:
            required_slots = _PARAM_REQUIRED_INTENTS[intent_name]
            has_any_param = any(
                slots.get(s) and str(slots.get(s)).strip()
                for s in required_slots
            )
            if not has_any_param:
                return False
        
        # logger.info(f"Processing Semantic Intent: {intent_name} for {user_id}")
        prefs = await self.adapter.config_handler.get_session_prefs(session_id=session_id, qq_user_id=user_id)
        is_master = self.adapter._is_master(user_id)

        # Parse context from session_id
        parts = session_id.split("_")
        msg_type = "private"
        group_id = ""
        if len(parts) >= 3 and parts[0] == "group":
            msg_type = "group"
            group_id = parts[1]
        
        # Helper to invoke command handler with correct context
        async def _invoke_cmd(cmd_text, arg_text=""):
            full_cmd = f"{cmd_text} {arg_text}".strip()
            return await self.adapter._try_handle_command(
                session_id=session_id,
                msg_type=msg_type,
                qq_user_id=user_id,
                raw_message=full_cmd,
                group_id=group_id
            )

        if intent_name == "CLEAR_MEMORY":
            return await _invoke_cmd("/clear")

        elif intent_name == "CLEAR_LOCAL_MEMORY":
            if not is_master:
                await self.send_text(session_id, "只有 Master 才能彻底清除记忆哦。")
                return True
            return await _invoke_cmd("/清除本地记忆", "confirm")

        elif intent_name == "TOGGLE_DEBUG_MODE":
            if not is_master:
                await self.send_text(session_id, "权限不足")
                return True
            return await _invoke_cmd("/调试模式")
            
        elif intent_name == "SHOW_STATUS":
            # 语义识别的查看状态，先获取数据，然后让 AI 汇报，而不是直接扔图
            data = await self.adapter.dashboard_handler.fetch_dashboard_data(session_id, prefs)
            if not data:
                await self.send_text(session_id, "获取系统状态失败，请稍后再试。")
                return True

            # 简化数据以适应 Prompt
            summary = {
                "health": data.get("health", {}).get("status", "unknown"),
                "cpu": f"{data.get('resources', {}).get('cpu_usage', 0):.1f}%",
                "mem": f"{data.get('resources', {}).get('memory_usage', 0):.1f}%",
                "gpu": f"{data.get('resources', {}).get('gpu_usage', 0):.1f}%" if data.get("resources", {}).get("gpu_usage") is not None else "N/A",
                "model": data.get("resources", {}).get("active_model", "unknown"),
                "memories": data.get("memory_stats", {}).get("total_memories", 0),
                "energy": data.get("life_status", {}).get("life", {}).get("energy"),
                "mood": data.get("life_status", {}).get("life", {}).get("mood"),
                "emotion": self.adapter._session_emotions.get(session_id, {}),
                "scheduler": data.get("health", {}).get("services", {}).get("scheduler_engine", {}).get("status", "unknown")
            }
            report_msg = f"[系统状态汇报请求]\n当前核心数据：{json.dumps(summary, ensure_ascii=False)}\n请你作为 Aveline，用你的语气向用户简单汇报一下你现在的身体状况或系统运行情况。不需要太专业，像日常聊天一样汇报即可。"
            session = self.adapter.sessions.get(session_id)
            if session:
                await session.send_text(report_msg, model=prefs.get("chat_model"))
            return True
            
        elif intent_name == "SHOW_HELP":
            return await _invoke_cmd("/help")

        elif intent_name == "SHOW_MODULE_DOC":
            module_hint = ""
            try:
                t = str(text or "").strip()
                m2 = re.search(
                    r"(?:模块|功能)\s*(?:介绍|说明|文档|指南|readme)\s*([\w\-\u4e00-\u9fa5/]+)",
                    t,
                    flags=re.IGNORECASE,
                )
                if m2:
                    module_hint = str(m2.group(1) or "").strip()
            except Exception:
                module_hint = ""
            return await _invoke_cmd("/模块", module_hint)

        elif intent_name == "LIST_MODELS":
            return await _invoke_cmd("/模型")
             
        elif intent_name == "LIST_VOICES":
            # 如果用户其实是想听语音，而不是看列表，则流转到聊天
            if self.adapter._wants_voice_reply(text):
                return False
            return await _invoke_cmd("/参考音频")
             
        elif intent_name == "SWITCH_MODEL":
            if not is_master:
                await self.send_text(session_id, "权限不足")
                return True
            # 尝试提取模型名称
            model_name = str(slots.get("model_name") or "").strip()
            if not model_name:
                # 增强的正则提取，支持更多自然语言句式
                # 1. 尝试匹配 "模型" 前面的词
                m = re.search(r"(?:切换到|换成|切到|切成|使用|用|变成|变|改用|改成)\s*([a-zA-Z0-9\s\._\-\u4e00-\u9fa5]+?)(?:的模型|模型|$)", text)
                if m:
                    model_name = m.group(1).strip()
                else:
                    # 2. 尝试匹配 "模型" 后面的词 (如果用户说 "模型换成xxx")
                    m2 = re.search(r"模型(?:切换到|换成|切到|切成|使用|用|变成|变|改用|改成)\s*([a-zA-Z0-9\s\._\-\u4e00-\u9fa5]+)", text)
                    if m2:
                        model_name = m2.group(1).strip()
            
            if model_name:
                # 再次清理 model_name，去除可能残留的标点
                model_name = model_name.strip(".,!?;:。，！？；：")
                handled = await self.adapter.resource_handler.handle_switch_model(session_id, model_name, prefs, user_id)
                return handled if handled is not None else True
            else:
                # 如果没提取到模型名，为了防止误判闲聊（如"本地模型比云端模型好用"被识别为SWITCH_MODEL），
                # 这里不应该直接提示"请告诉我你想切换到哪个模型"，而是应该放弃指令处理，回退到普通聊天。
                # 因为如果用户真的是想切换模型但没说清楚，他会再试一次；
                # 但如果用户只是在闲聊，突然被问"你想切换到哪个模型"会很突兀。
                # 所以我们返回 False，让消息继续流转到 Chat Handler。
                return False

        elif intent_name == "SWITCH_MODEL_HINT":
            await self.send_text(session_id, "请使用 '/切模型 <模型名>' 指令，或者发送 '/模型列表' 查看可用模型。")
            return True

        elif intent_name == "SWITCH_PERSONA":
            if not is_master:
                await self.send_text(session_id, "权限不足")
                return True
            persona_name = str(slots.get("persona_name") or "").strip()
            if not persona_name:
                m = re.search(
                    r"(?:切换到|换成|切到|切成|使用)\s*([a-zA-Z0-9\s\._\-\u4e00-\u9fa5/]+?)(?:的?人设|的?性格|的?角色|人设|性格|角色|$)",
                    text,
                )
                if m:
                    persona_name = m.group(1).strip()
                else:
                    clean = text
                    for kw in ["给我", "切换到", "换成", "切到", "切成", "使用", "人设", "性格", "角色"]:
                        clean = clean.replace(kw, "")
                    persona_name = clean.strip()

            if not persona_name:
                # 如果完全没提取到，可能语义识别有误，也流转到聊天
                return False

            handled = await self.adapter.resource_handler.handle_switch_persona(session_id, persona_name, prefs, user_id)
            # 如果 handle 返回 False (未找到匹配)，则继续向下流转到聊天
            return handled if handled is not None else True
                
        elif intent_name == "TOGGLE_LATENCY":
            if not is_master:
                await self.send_text(session_id, "权限不足")
                return True
            # 提取开关状态
            arg = str(slots.get("state") or "").strip().lower()
            if arg not in {"on", "off"}:
                arg = ""
                if any(x in text for x in ("开启", "打开", "启用", "on", "enable")):
                    arg = "on"
                elif any(x in text for x in ("关闭", "禁用", "off", "disable")):
                    arg = "off"
            return await _invoke_cmd("/latency", arg)
            
        elif intent_name == "TOGGLE_REPLY_MODE":
            if not is_master:
                await self.send_text(session_id, "权限不足")
                return True
            arg = ""
            if any(x in text for x in ("全部", "所有", "全回复", "all")):
                arg = "all"
            elif any(x in text for x in ("艾特", "仅艾特", "at", "at_only")):
                arg = "at"
            return await _invoke_cmd("/回复模式", arg)

        elif intent_name == "TOGGLE_STUDY_MODE":
            arg = ""
            if any(x in text for x in ("开启", "打开", "启用", "on", "enable", "进入")):
                arg = "on"
            elif any(x in text for x in ("关闭", "禁用", "off", "disable", "退出")):
                arg = "off"
            return await _invoke_cmd("/学习模式", arg)

        elif intent_name == "TOGGLE_PRIVACY_MODE":
            arg = ""
            if any(x in text for x in ("开启", "打开", "启用", "on", "enable", "进入")):
                arg = "on"
            elif any(x in text for x in ("关闭", "禁用", "off", "disable", "退出")):
                arg = "off"
            return await _invoke_cmd("/私密模式", arg)

        elif intent_name == "DISABLE_VOICE_REPLY":
            prefs["reply_voice_only"] = False
            prefs["session_tts_enabled"] = False
            prefs["reply_voice_once"] = False
            try:
                await self.adapter.config_handler.persist_user_override(str(user_id or ""), prefs)
            except Exception:
                pass
            await self.send_text(session_id, "好，已切回文字回复，不再发语音。")
            return True
            
        elif intent_name == "SEND_VOICE":
            # 显式识别为发送语音意图，直接流转到聊天逻辑处理
            return False
        
        elif intent_name == "SWITCH_TTS_MODE":
            if not is_master:
                await self.send_text(session_id, "权限不足")
                return True
            # 提取模式
            mode = ""
            if any(x in text for x in ("cloud", "云端", "火山", "volcano")):
                mode = "cloud"
            elif any(x in text for x in ("local", "本地", "qwen3")):
                mode = "local"
            if mode:
                return await _invoke_cmd("/tts模式", mode)
            else:
                await self.send_text(session_id, "用法：/tts模式 cloud（云端）或 /tts模式 local（本地）")
                return True
            
        return False
