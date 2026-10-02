"""Telegram 命令处理 Mixin。

包含所有命令处理和路由逻辑：
- 基础命令：/start /help /status
- 模型管理：/模型 /切模型
- 人设管理：/人设 /切人设
- 记忆管理：/清除短期记忆 /清除记忆
- TTS 语音：/tts
- 生命控制：/唤醒 /打断 /跳过 /继续聊
- 骰子游戏：/骰子 /飞镖 /老虎机 /篮筐
- Inline 按钮回调：切模型/切人设的按钮点击

本 Mixin 依赖主类 TelegramAdapter 提供以下属性/方法：
- self.application, self.http_client, self.persona_filename
- self._list_cache, self._is_master(), self.send_text_to_chat()
- self._send_dice(), self._send_voice_response()
"""
from __future__ import annotations

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from clients.bots.telegram.settings import logger


class CommandHandlersMixin:
    """命令处理 Mixin：提供所有 Telegram Bot 命令的处理逻辑。"""

    # ===== 基础命令（Telegram Handler 接口）=====

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat_id = update.effective_chat.id
        if not self._is_master(user.id):
            return
        logger.info(f"用户 {user.id} 启动机器人")
        welcome = (
            f"你好，{user.first_name}！\n\n"
            "我是小优 AI 助手，可以和你聊天、处理图片、识别语音。\n\n"
            "直接发送消息即可开始对话！"
        )
        await self.send_text_to_chat(str(chat_id), welcome)

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_master(update.effective_user.id):
            return
        help_text = (
            "使用帮助：\n\n"
            "对话：直接发送文本消息\n"
            "图片：发送图片，我可以识别内容\n"
            "语音：发送语音消息，我可以识别语音内容\n"
            "命令：/start /help /status"
        )
        await self.send_text_to_chat(str(update.effective_chat.id), help_text)

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_master(update.effective_user.id):
            return
        status, data = await self.http_client.request("GET", "/api/v1/health", timeout_seconds=3.0)
        if status == 200:
            await self.send_text_to_chat(str(update.effective_chat.id), "✅ 系统运行正常")
        else:
            await self.send_text_to_chat(str(update.effective_chat.id), "⚠️ 系统状态异常")

    # ===== Inline 按钮回调 =====

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 Inline 按钮回调（/模型 /人设 列表点击）。"""
        query = update.callback_query
        if not query:
            return
        if not self._is_master(query.from_user.id):
            return
        # 必须调 answer()，否则按钮会一直转圈
        await query.answer()
        data = str(query.data or "")
        chat_id_str = str(query.message.chat_id)
        # 格式：sm:<idx> 切模型 / sp:<idx> 切人设
        if data.startswith("sm:"):
            idx_str = data[3:].strip()
            await self._cmd_switch_model(chat_id_str, idx_str)
        elif data.startswith("sp:"):
            idx_str = data[3:].strip()
            await self._cmd_switch_persona(chat_id_str, idx_str)
        else:
            logger.debug(f"未知 callback data: {data}")

    # ===== 骰子命令 =====

    async def _cmd_dice(self, chat_id_str: str, rest: str):
        """/骰子：掷一个骰子"""
        await self._send_dice(chat_id_str, "🎲")

    async def _cmd_dart(self, chat_id_str: str, rest: str):
        """/飞镖：掷飞镖"""
        await self._send_dice(chat_id_str, "🎯")

    async def _cmd_slot(self, chat_id_str: str, rest: str):
        """/老虎机：拉老虎机"""
        await self._send_dice(chat_id_str, "🎰")

    async def _cmd_basketball(self, chat_id_str: str, rest: str):
        """/篮筐：投篮"""
        await self._send_dice(chat_id_str, "🏀")

    # ===== 命令路由系统 =====

    def _build_command_routes(self) -> dict[str, tuple]:
        """构建命令别名表：alias -> (handler_name, master_only, description)"""
        return {
            # 帮助
            "帮助": ("_cmd_help", False, "显示命令列表"),
            "help": ("_cmd_help", False, "显示命令列表"),
            "h": ("_cmd_help", False, "显示命令列表"),
            "菜单": ("_cmd_help", False, "显示命令列表"),
            "?": ("_cmd_help", False, "显示命令列表"),
            # 状态
            "状态": ("_cmd_status", False, "查看后端状态、当前模型与人设"),
            "status": ("_cmd_status", False, "查看后端状态、当前模型与人设"),
            # 模型列表
            "模型": ("_cmd_models", False, "列出可用 LLM 模型"),
            "models": ("_cmd_models", False, "列出可用 LLM 模型"),
            "model": ("_cmd_models", False, "列出可用 LLM 模型"),
            # 人设列表
            "人设": ("_cmd_personas", False, "列出可用人设"),
            "persona": ("_cmd_personas", False, "列出可用人设"),
            "personas": ("_cmd_personas", False, "列出可用人设"),
            # 切模型（Master only）
            "切模型": ("_cmd_switch_model", True, "切换 LLM 模型：/切模型 <名称/序号>"),
            "switchmodel": ("_cmd_switch_model", True, "切换 LLM 模型"),
            "switch_model": ("_cmd_switch_model", True, "切换 LLM 模型"),
            # 切人设（Master only）
            "切人设": ("_cmd_switch_persona", True, "切换人设：/切人设 <名称/序号/filename>"),
            "切换人设": ("_cmd_switch_persona", True, "切换人设"),
            "switchpersona": ("_cmd_switch_persona", True, "切换人设"),
            "switch_persona": ("_cmd_switch_persona", True, "切换人设"),
            # 清除短期记忆
            "清除短期记忆": ("_cmd_clear_short_memory", False, "清除当前会话上下文记忆"),
            "reset": ("_cmd_clear_short_memory", False, "清除当前会话上下文记忆"),
            "clear": ("_cmd_clear_short_memory", False, "清除当前会话上下文记忆"),
            # 清除全部加权记忆（Master only）
            "清除记忆": ("_cmd_clear_all_memory", True, "清除所有加权记忆"),
            "clearall": ("_cmd_clear_all_memory", True, "清除所有加权记忆"),
            "clear_all": ("_cmd_clear_all_memory", True, "清除所有加权记忆"),
            # TTS 语音合成
            "tts": ("_cmd_tts", False, "用语音说指定的话：/tts 你好呀"),
            "语音": ("_cmd_tts", False, "用语音说指定的话：/语音 你好呀"),
            "说": ("_cmd_tts", False, "用语音说指定的话：/说 你好呀"),
            # 生命/活动控制（Master only，转发后端 /api/v1/life/* ）
            "唤醒": ("_cmd_wake", True, "立即唤醒角色"),
            "wake": ("_cmd_wake", True, "立即唤醒角色"),
            "叫醒": ("_cmd_wake", True, "立即唤醒角色"),
            "forcewake": ("_cmd_wake", True, "立即唤醒角色"),
            "打断": ("_cmd_interrupt", True, "打断当前活动进入聊天窗口"),
            "interrupt": ("_cmd_interrupt", True, "打断当前活动"),
            "busywake": ("_cmd_interrupt", True, "打断当前活动"),
            "跳过活动": ("_cmd_skip", True, "跳过当前活动，不再提醒回去做事"),
            "跳过": ("_cmd_skip", True, "跳过当前活动"),
            "skip": ("_cmd_skip", True, "跳过当前活动"),
            "skipactivity": ("_cmd_skip", True, "跳过当前活动"),
            "继续聊": ("_cmd_extend", True, "延长聊天窗口时间（最多3次）"),
            "延长": ("_cmd_extend", True, "延长聊天窗口时间"),
            "extend": ("_cmd_extend", True, "延长聊天窗口时间"),
            "extendchat": ("_cmd_extend", True, "延长聊天窗口时间"),
            # 骰子/小游戏
            "骰子": ("_cmd_dice", False, "掷骰子 🎲"),
            "dice": ("_cmd_dice", False, "掷骰子 🎲"),
            "飞镖": ("_cmd_dart", False, "掷飞镖 🎯"),
            "dart": ("_cmd_dart", False, "掷飞镖 🎯"),
            "老虎机": ("_cmd_slot", False, "拉老虎机 🎰"),
            "slot": ("_cmd_slot", False, "拉老虎机 🎰"),
            "篮筐": ("_cmd_basketball", False, "投篮 🏀"),
            "basketball": ("_cmd_basketball", False, "投篮 🏀"),
        }

    async def _try_handle_command(self, chat_id_str: str, raw_message: str, user_id) -> bool:
        """解析并分发命令。命中返回 True，未命中返回 False。

        支持 / 和 ／ 作为命令前缀，与 QQ 适配器一致。
        """
        if not raw_message:
            return False
        m = str(raw_message).lstrip()
        if not (m.startswith("/") or m.startswith("／")):
            return False
        cmd_line = m.lstrip("/／").strip()
        if not cmd_line:
            await self._cmd_help(chat_id_str, "")
            return True

        parts = cmd_line.split(None, 1)
        cmd = str(parts[0] or "").strip().lower()
        rest = str(parts[1] if len(parts) > 1 else "").strip()

        routes = self._build_command_routes()
        entry = routes.get(cmd)
        if entry is None:
            return False
        handler_name, master_only, _desc = entry
        if master_only and not self._is_master(user_id):
            await self.send_text_to_chat(chat_id_str, "权限不足：该命令仅 Master 可用")
            return True
        handler = getattr(self, handler_name, None)
        if handler is None:
            return False
        await handler(chat_id_str, rest)
        return True

    @staticmethod
    def _session_id_from_chat(chat_id_str: str) -> str:
        raw = str(chat_id_str or "").strip()
        if raw.startswith("tg_"):
            return raw
        return f"tg_{raw}"

    # ===== 命令实现 =====

    async def _cmd_help(self, chat_id_str: str, rest: str):
        routes = self._build_command_routes()
        seen = set()
        lines = ["📖 可用命令：", ""]
        for alias, (handler_name, master_only, desc) in routes.items():
            if handler_name in seen:
                continue
            seen.add(handler_name)
            tag = " [Master]" if master_only else ""
            lines.append(f"/{alias}{tag} - {desc}")
        lines.append("")
        lines.append("💡 直接发送文本即可聊天；发送图片可识别内容；发送语音可转文字。")
        await self.send_text_to_chat(chat_id_str, "\n".join(lines))

    async def _cmd_status(self, chat_id_str: str, rest: str):
        status, data = await self.http_client.request("GET", "/api/v1/health", timeout_seconds=3.0)
        health_ok = (status == 200)

        cur_model = (self._list_cache.get("model") or {}).get("current")
        if not cur_model:
            _, mdata = await self.http_client.request("GET", "/api/v1/models", timeout_seconds=5.0)
            if isinstance(mdata, dict):
                cur_model = mdata.get("current")
                self._list_cache["model"] = {"data": mdata.get("available") or [], "current": cur_model}

        cur_persona = (self._list_cache.get("persona") or {}).get("current")
        if not cur_persona:
            _, pdata = await self.http_client.request("GET", "/api/v1/personas/active", timeout_seconds=5.0)
            if isinstance(pdata, dict):
                cur_persona = pdata.get("filename") or ""
                self._list_cache["persona"] = {"current": cur_persona}

        lines = ["📊 系统状态", ""]
        lines.append(f"后端: {'✅ 正常' if health_ok else '⚠️ 异常'}")
        if isinstance(cur_model, dict):
            lines.append(f"当前模型: {cur_model.get('provider','')}/{cur_model.get('model','')}")
        if cur_persona:
            lines.append(f"当前人设: {cur_persona}")
        await self.send_text_to_chat(chat_id_str, "\n".join(lines))

    async def _cmd_models(self, chat_id_str: str, rest: str):
        status, data = await self.http_client.request("GET", "/api/v1/models", timeout_seconds=10.0)
        if status != 200 or not isinstance(data, dict):
            await self.send_text_to_chat(chat_id_str, f"获取模型列表失败: {data}")
            return
        models = data.get("available") or []
        current = data.get("current") or {}
        self._list_cache["model"] = {"data": models, "current": current}

        cur_provider = str(current.get("provider") or "").strip().lower()
        cur_model = str(current.get("model") or "").strip().lower()

        # 构建 Inline 按钮（每行2个，最多10行=20个模型）
        buttons: list[list[InlineKeyboardButton]] = []
        row: list[InlineKeyboardButton] = []
        lines = ["🤖 可用 LLM 模型：", ""]
        for i, m in enumerate(models, 1):
            if not isinstance(m, dict):
                continue
            name = str(m.get("name") or m.get("id") or m.get("model") or "")
            provider = str(m.get("provider") or "")
            mp = str(m.get("model") or m.get("id") or "").strip().lower()
            mark = ""
            if provider.strip().lower() == cur_provider and mp and mp == cur_model:
                mark = " ✅"
            lines.append(f"{i}. [{provider}] {name}{mark}")

            # 按钮：显示序号+名称，callback_data 用 sm:<idx>
            btn_text = f"{i}. {name[:12]}{'✅' if mark else ''}"
            row.append(InlineKeyboardButton(btn_text, callback_data=f"sm:{i}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        lines.append("")
        lines.append("👇 点按钮切换，或用 /切模型 <序号或名称>")
        markup = InlineKeyboardMarkup(buttons) if buttons else None
        await self.send_text_to_chat(chat_id_str, "\n".join(lines), reply_markup=markup)

    async def _cmd_personas(self, chat_id_str: str, rest: str):
        status, data = await self.http_client.request("GET", "/api/v1/personas", timeout_seconds=10.0)
        if status != 200 or not isinstance(data, list):
            await self.send_text_to_chat(chat_id_str, f"获取人设列表失败: {data}")
            return
        # 当前人设
        cur_persona = (self._list_cache.get("persona") or {}).get("current")
        if not cur_persona:
            _, pdata = await self.http_client.request("GET", "/api/v1/personas/active", timeout_seconds=5.0)
            if isinstance(pdata, dict):
                cur_persona = pdata.get("filename") or ""
        self._list_cache["persona"] = {"data": data, "current": cur_persona}

        # 构建 Inline 按钮（每行1个）
        buttons: list[list[InlineKeyboardButton]] = []
        lines = ["👤 可用人设：", ""]
        for i, p in enumerate(data, 1):
            if not isinstance(p, dict):
                continue
            filename = str(p.get("filename") or "")
            name = str(p.get("name") or filename)
            mark = " ✅" if cur_persona and filename == cur_persona else ""
            lines.append(f"{i}. {name} ({filename}){mark}")

            btn_text = f"{i}. {name[:20]}{'✅' if mark else ''}"
            buttons.append([InlineKeyboardButton(btn_text, callback_data=f"sp:{i}")])

        lines.append("")
        lines.append("👇 点按钮切换，或用 /切人设 <序号或名称>")
        markup = InlineKeyboardMarkup(buttons) if buttons else None
        await self.send_text_to_chat(chat_id_str, "\n".join(lines), reply_markup=markup)

    async def _cmd_switch_model(self, chat_id_str: str, rest: str):
        arg = str(rest or "").strip()
        if not arg:
            await self.send_text_to_chat(chat_id_str, "用法: /切模型 <名称或序号>\n先用 /模型 查看列表")
            return

        cache = self._list_cache.get("model") or {}
        models = cache.get("data") or []
        if not models:
            status, data = await self.http_client.request("GET", "/api/v1/models", timeout_seconds=10.0)
            if status != 200 or not isinstance(data, dict):
                await self.send_text_to_chat(chat_id_str, f"获取模型列表失败: {data}")
                return
            models = data.get("available") or []
            cache = {"data": models, "current": data.get("current")}

        target = None
        # 1. 序号
        try:
            idx = int(arg) - 1
            if 0 <= idx < len(models):
                target = models[idx]
        except ValueError:
            target = None

        # 2. 模糊匹配名称
        if target is None:
            q = arg.lower()
            best, best_score = None, 0
            for m in models:
                if not isinstance(m, dict):
                    continue
                hay = " ".join(str(x or "") for x in [
                    m.get("id"), m.get("name"), m.get("model"), m.get("path")
                ]).strip().lower()
                s = 100 if hay == q else (50 if hay.startswith(q) else (10 if q in hay else 0))
                if s > best_score:
                    best_score, best = s, m
            if best and best_score > 0:
                target = best

        if not isinstance(target, dict):
            await self.send_text_to_chat(chat_id_str, f"未找到匹配的模型: {arg}\n先用 /模型 查看列表")
            return

        model_name = str(target.get("id") or target.get("model") or target.get("name") or "").strip()
        provider = str(target.get("provider") or "local").strip()
        path = str(target.get("path") or "").strip()

        # cloud: 格式直接用完整 path 解析
        body = {"model_name": model_name, "provider": provider}
        if path.startswith("cloud:"):
            parts = path.split(":")
            if len(parts) >= 3:
                provider = parts[1]
                model_name = parts[3] if len(parts) >= 4 else parts[2]
                body = {"model_name": model_name, "provider": provider}

        status, data = await self.http_client.request("POST", "/api/v1/models/switch", json_body=body, timeout_seconds=30.0)
        if status == 200 and isinstance(data, dict) and data.get("success") is not False:
            new_current = data.get("current") or {"provider": provider, "model": model_name}
            self._list_cache["model"] = {"data": models, "current": new_current}
            await self.send_text_to_chat(chat_id_str, f"✅ LLM 模型已切换: {provider}/{model_name}")
        else:
            err = (data.get("error") or data.get("message") or data.get("detail") or "API Error") if isinstance(data, dict) else "API Error"
            await self.send_text_to_chat(chat_id_str, f"❌ 切换模型失败: {err}")

    async def _cmd_switch_persona(self, chat_id_str: str, rest: str):
        arg = str(rest or "").strip()
        if not arg:
            await self.send_text_to_chat(chat_id_str, "用法: /切人设 <名称/序号/filename>\n先用 /人设 查看列表")
            return

        cache = self._list_cache.get("persona") or {}
        personas = cache.get("data") or []
        if not personas:
            status, data = await self.http_client.request("GET", "/api/v1/personas", timeout_seconds=10.0)
            if status != 200 or not isinstance(data, list):
                await self.send_text_to_chat(chat_id_str, f"获取人设列表失败: {data}")
                return
            personas = data
            cache = {"data": personas, "current": cache.get("current")}

        target = None
        # 1. 序号
        try:
            idx = int(arg) - 1
            if 0 <= idx < len(personas):
                target = personas[idx]
        except ValueError:
            target = None

        # 2. 名称/filename 匹配
        if target is None:
            q = arg.lower()
            exact, partial = [], []
            for p in personas:
                if not isinstance(p, dict):
                    continue
                fn = str(p.get("filename") or "").strip()
                name = str(p.get("name") or "").strip()
                if fn.lower() == q or name.lower() == q:
                    exact.append(p)
                elif q and (q in fn.lower() or q in name.lower()):
                    partial.append(p)
            target = exact[0] if exact else (partial[0] if partial else None)

        if not isinstance(target, dict):
            await self.send_text_to_chat(chat_id_str, f"未找到匹配的人设: {arg}\n先用 /人设 查看列表")
            return

        filename = str(target.get("filename") or "").strip()
        if not filename:
            await self.send_text_to_chat(chat_id_str, "人设条目缺少 filename，无法切换")
            return

        cur = str(cache.get("current") or "").strip()
        if cur and filename == cur:
            await self.send_text_to_chat(chat_id_str, f"当前已是该人设: {filename}")
            return

        status, data = await self.http_client.request(
            "POST", "/api/v1/personas/switch", json_body={"filename": filename}, timeout_seconds=30.0
        )
        if status == 200 and isinstance(data, dict) and str(data.get("status") or "").lower() == "success":
            # 更新 adapter 当前人设，让后续对话走新人设
            self.persona_filename = filename
            self._list_cache["persona"] = {"data": personas, "current": filename}
            await self.send_text_to_chat(chat_id_str, f"✅ 人设已切换: {filename}")
        else:
            err = (data.get("detail") or data.get("message") or "API Error") if isinstance(data, dict) else "API Error"
            await self.send_text_to_chat(chat_id_str, f"❌ 切换人设失败: {err}")

    async def _cmd_clear_short_memory(self, chat_id_str: str, rest: str):
        session_id = self._session_id_from_chat(chat_id_str)
        status, data = await self.http_client.request(
            "POST", "/api/v1/memories/clear",
            json_body={"user_id": session_id, "mode": "short"},
            timeout_seconds=10.0,
        )
        if status == 200 and isinstance(data, dict) and str(data.get("status") or "").lower() == "success":
            await self.send_text_to_chat(chat_id_str, "✅ 短期记忆已清除")
        else:
            err = (data.get("message") or "API Error") if isinstance(data, dict) else "API Error"
            await self.send_text_to_chat(chat_id_str, f"❌ 清除短期记忆失败: {err}")

    async def _cmd_clear_all_memory(self, chat_id_str: str, rest: str):
        session_id = self._session_id_from_chat(chat_id_str)
        status, data = await self.http_client.request(
            "DELETE", "/api/v1/memories", params={"user_id": session_id}, timeout_seconds=10.0
        )
        if status == 200 and isinstance(data, dict) and str(data.get("status") or "").lower() == "success":
            count = data.get("count", "?")
            await self.send_text_to_chat(chat_id_str, f"✅ 已清除 {count} 条加权记忆")
        else:
            err = (data.get("message") or "API Error") if isinstance(data, dict) else "API Error"
            await self.send_text_to_chat(chat_id_str, f"❌ 清除记忆失败: {err}")

    async def _cmd_tts(self, chat_id_str: str, rest: str):
        """用语音说指定的话：/tts <文本>"""
        text = str(rest or "").strip()
        if not text:
            await self.send_text_to_chat(chat_id_str, "用法: /tts <要说的文本>\n示例: /tts 你好呀，我是小优")
            return
        ok = await self._send_voice_response(chat_id_str, text)
        if not ok:
            await self.send_text_to_chat(chat_id_str, "❌ 语音合成失败，请检查后端 TTS 服务")

    # ===== 生命/活动控制 =====

    def _build_life_payload(self, chat_id_str: str, rest: str) -> dict:
        """构建生命控制命令的请求体（参照 QQ 的 _resolve_wake_payload）。"""
        session_id = self._session_id_from_chat(chat_id_str)
        persona_filename = str(getattr(self, "persona_filename", "") or "").strip()
        # 复用 session.py 的 conversation_id 构建逻辑
        try:
            from clients.bots.telegram.session import build_persona_conversation_id
            conversation_id = build_persona_conversation_id(session_id, persona_filename) if persona_filename else session_id
        except Exception:
            conversation_id = session_id
        message = str(rest or "").strip() or "Telegram命令触发"
        payload = {
            "conversation_id": conversation_id,
            "message": message,
        }
        if persona_filename:
            payload["persona_filename"] = persona_filename
        return payload

    async def _cmd_wake(self, chat_id_str: str, rest: str):
        """/唤醒：立即唤醒角色"""
        payload = self._build_life_payload(chat_id_str, rest)
        status, data = await self.http_client.request(
            "POST", "/api/v1/life/sleep/wake", json_body=payload, timeout_seconds=15.0
        )
        if status != 200 or not isinstance(data, dict):
            await self.send_text_to_chat(chat_id_str, f"❌ 唤醒失败 (HTTP {status})")
            return
        action = str(data.get("action") or "").strip()
        role = str(data.get("role_id") or "").strip() or "当前角色"
        summary = data.get("sleep_summary") if isinstance(data.get("sleep_summary"), dict) else {}
        phase = str(summary.get("phase") or "unknown")
        if action == "woken_up":
            await self.send_text_to_chat(chat_id_str, f"✅ 已立即唤醒 {role}，当前状态：{phase}")
        elif action == "already_awake":
            await self.send_text_to_chat(chat_id_str, f"ℹ️ {role} 当前没在睡，状态：{phase}")
        else:
            err = str(data.get("message") or data.get("error") or "唤醒失败").strip()
            await self.send_text_to_chat(chat_id_str, f"❌ {err}")

    async def _cmd_interrupt(self, chat_id_str: str, rest: str):
        """/打断：打断当前活动进入聊天窗口"""
        payload = self._build_life_payload(chat_id_str, rest)
        status, data = await self.http_client.request(
            "POST", "/api/v1/life/activity/interrupt", json_body=payload, timeout_seconds=15.0
        )
        if status != 200 or not isinstance(data, dict):
            await self.send_text_to_chat(chat_id_str, f"❌ 打断失败 (HTTP {status})")
            return
        action = str(data.get("action") or "").strip()
        role = str(data.get("role_id") or "").strip() or "当前角色"
        activity = str(data.get("activity") or "unknown").strip()
        window_seconds = int(data.get("window_seconds") or 0)
        if action == "interrupted":
            await self.send_text_to_chat(
                chat_id_str,
                f"✅ 已打断 {role} 的 {activity}，接下来约 {window_seconds} 秒内会优先和你聊天。"
            )
        elif action == "already_available":
            await self.send_text_to_chat(chat_id_str, f"ℹ️ {role} 现在本来就在空闲状态，不用额外打断。")
        elif action == "already_skipped":
            remaining = str(data.get("remaining_display") or "").strip()
            suffix = f"（约 {remaining}）" if remaining else ""
            await self.send_text_to_chat(
                chat_id_str, f"ℹ️ {role} 当前活动已经被跳过{suffix}，这段时间都能继续聊天。"
            )
        elif action == "sleeping_use_wake":
            await self.send_text_to_chat(chat_id_str, f"ℹ️ {role} 当前属于睡眠状态，请先用 /唤醒。")
        else:
            err = str(data.get("message") or data.get("error") or "打断失败").strip()
            await self.send_text_to_chat(chat_id_str, f"❌ {err}")

    async def _cmd_skip(self, chat_id_str: str, rest: str):
        """/跳过活动：跳过当前活动，不再提醒回去做事"""
        payload = self._build_life_payload(chat_id_str, rest)
        status, data = await self.http_client.request(
            "POST", "/api/v1/life/activity/skip", json_body=payload, timeout_seconds=15.0
        )
        if status != 200 or not isinstance(data, dict):
            await self.send_text_to_chat(chat_id_str, f"❌ 跳过活动失败 (HTTP {status})")
            return
        action = str(data.get("action") or "").strip()
        role = str(data.get("role_id") or "").strip() or "当前角色"
        activity = str(data.get("activity") or "unknown").strip()
        remaining = str(data.get("remaining_display") or "").strip()
        if action in ("skipped", "auto_skipped"):
            prefix = "✅ 已跳过" if action == "skipped" else "✅ 已自动打断并跳过"
            await self.send_text_to_chat(
                chat_id_str,
                f"{prefix} {role} 的 {activity}，接下来约 {remaining} 内继续聊天，不会再提醒回去做事了。"
            )
        elif action == "no_interrupt_window":
            await self.send_text_to_chat(
                chat_id_str, f"ℹ️ {role} 当前没有活跃的中断窗口，请先用 /打断 打断忙碌状态。"
            )
        elif action == "already_available":
            await self.send_text_to_chat(chat_id_str, f"ℹ️ {role} 现在本来就在空闲状态，不需要跳过活动。")
        elif action == "sleeping_use_wake":
            await self.send_text_to_chat(chat_id_str, f"ℹ️ {role} 当前属于睡眠状态，请先用 /唤醒。")
        else:
            err = str(data.get("message") or data.get("error") or "跳过失败").strip()
            await self.send_text_to_chat(chat_id_str, f"❌ {err}")

    async def _cmd_extend(self, chat_id_str: str, rest: str):
        """/继续聊：延长聊天窗口时间（最多3次）"""
        extend_seconds = 300
        rest_stripped = str(rest or "").strip()
        if rest_stripped and rest_stripped.isdigit():
            extend_seconds = max(60, min(600, int(rest_stripped)))
        payload = self._build_life_payload(chat_id_str, rest)
        payload["extend_seconds"] = extend_seconds
        status, data = await self.http_client.request(
            "POST", "/api/v1/life/activity/extend", json_body=payload, timeout_seconds=15.0
        )
        if status != 200 or not isinstance(data, dict):
            await self.send_text_to_chat(chat_id_str, f"❌ 延长窗口失败 (HTTP {status})")
            return
        action = str(data.get("action") or "").strip()
        role = str(data.get("role_id") or "").strip() or "当前角色"
        extended_count = int(data.get("extended_count") or 0)
        remaining = int(data.get("remaining_seconds") or 0)
        if action == "extended":
            await self.send_text_to_chat(
                chat_id_str,
                f"✅ 已延长 {role} 的聊天窗口 {extend_seconds} 秒，当前剩余约 {remaining} 秒（已延长 {extended_count} 次）。"
            )
        elif action == "no_window_or_max_extended":
            await self.send_text_to_chat(
                chat_id_str,
                f"ℹ️ {role} 当前没有活跃的中断窗口，或已达到延长上限（最多 3 次）。请先用 /打断。"
            )
        else:
            err = str(data.get("message") or data.get("error") or "延长失败").strip()
            await self.send_text_to_chat(chat_id_str, f"❌ {err}")
