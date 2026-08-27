from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from clients.bots.handlers.command_router_support import (
    handle_latency,
    handle_meme,
    handle_openclaw,
    handle_privacy_mode,
    handle_reply_mode,
    handle_sid,
    handle_study_mode,
    handle_voice_only,
    handle_web_search,
)
from clients.bots.handlers.command_router_session_support import (
    handle_activity_extend,
    handle_activity_interrupt,
    handle_activity_skip,
    handle_clear_all_memory,
    handle_clear_short_memory,
    handle_debug_mode,
    handle_history,
    handle_regenerate,
    handle_session_delete,
    handle_session_list,
    handle_session_rename,
    handle_sleep_wake,
    handle_split_toggle,
    handle_tts_mode,
)


@dataclass(frozen=True)
class CommandRoute:
    aliases: set[str]
    master_only: bool
    handler: Callable[..., Awaitable[bool]]
    description: str = ""  # 指令描述，用于 /help 显示


# 指令描述映射：第一个别名 -> 描述文本
_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "help": "指令速查菜单",
    "模块": "查看功能模块介绍（/模块 <模块名> 查看详情）",
    "状态": "总面板概览（别名 /面板），可加子命令：资源/服务/模块/记忆/会话/日程/用户/生物/情绪",
    "模型": "查看可用模型列表 (子命令: llm, 图像)",
    "参考音频": "查看可用语音参考音频列表",
    "人设": "查看可用人设列表",
    "切模型": "切换 LLM 或生图模型（/切模型 <名称/ID>）",
    "切人设": "切换当前人设（/切人设 <名称/序号/filename>）",
    "设置参考音频": "设置 TTS 参考音频（支持序号选择）",
    "生图": "使用当前生图模型生成图片（/生图 <提示词>）",
    "t2i": "Astar兼容：开关文本转图片模式",
    "llm": "Astar兼容：开关当前会话LLM聊天",
    "tts": "Astar兼容：开关当前会话文本转语音",
    "食物": "查看食物菜单",
    "库存": "查看食物背包（包含过期时间）",
    "买": "购买食物进入背包（支持 /买 19*10）",
    "吃": "从背包优先消耗并进食（无则花金币）",
    "喝": "快捷记录喝水，1=250ml（可写 /喝 2）",
    "学习": "记录学习并进入低打扰模式（/学习 结束 结束）",
    "搜索": "走 OpenClaw 联网搜索并结构化总结",
    "oc": "将任务交给 OpenClaw 执行并回报结果",
    "sid": "查看当前会话ID与来源信息（调试用）",
    "表情": "发送meme表情包（默认随机，可按分类）",
    "历史": "查看会话历史消息（默认当前会话）",
    "会话列表": "查看后端会话列表（最多展示20个）",
    "会话重命名": "【Master】重命名任意会话",
    "删除会话": "【Master】删除指定会话",
    "唤醒": "【Master】立即唤醒角色",
    "打断": "【Master】打断当前活动进入聊天窗口",
    "跳过活动": "【Master】跳过当前活动，不再提醒回去做事",
    "继续聊": "【Master】延长聊天窗口时间（最多3次）",
    "清除短期记忆": "清除当前上下文记忆（别名 /clear）",
    "清除本地记忆": "【Master】彻底删除本地所有历史记忆",
    "调试模式": "【Master】切换无状态模式（不保存历史）",
    "保存配置": "保存当前会话偏好",
    "学习模式": "快速切换学习模式（on=study，off=normal）",
    "私密模式": "快速切换私密模式（on=privacy，off=normal）",
    "模式": "切换系统偏好模式（study/normal/privacy/entertainment）",
    "仿生延迟": "开启/关闭模拟思考延迟",
    "回复模式": "切换群聊回复模式（all=全部回复，at=仅艾特）",
    "只语音": "【Master】仅语音回复（不再发送文字）",
    "截图": "【Master】抓取当前机器屏幕并回传",
    "文件": "【Master】在 workspace Study 目录执行文件操作",
    "批准": "【Master】批准高风险远程命令",
    "拒绝": "【Master】拒绝高风险远程命令",
    "tts模式": "【Master】切换TTS模式（cloud/local）",
    "重新生成": "重新生成上一条回复",
    "断句": "切换消息断句模式",
}


class CommandRouter:
    def __init__(self, adapter):
        self.adapter = adapter
        self._routes = self._build_routes()

    def _get_description(self, aliases: set[str]) -> str:
        """从第一个别名获取描述。"""
        for alias in aliases:
            if alias in _COMMAND_DESCRIPTIONS:
                return _COMMAND_DESCRIPTIONS[alias]
        return ""

    def _build_routes(self) -> list[CommandRoute]:
        # P1-7: 命令系统收口到 Aveline 主路由
        # 与 Aveline command_handler 冲突的英文别名（study/save/clear/latency/mode/memory 等）
        # 已从本地路由移除，这些命令将转发后端 Aveline 统一处理
        # 中文别名保留供本地使用（如 /清除短期记忆 /保存配置 /仿生延迟）
        return [
            CommandRoute({"help", "h", "?", "帮助", "菜单"}, False, self._help, self._get_description({"help"})),
            CommandRoute({"模块", "module", "modules", "readme", "docs", "文档", "指南", "说明", "功能介绍"}, False, self._module_docs, self._get_description({"模块"})),
            CommandRoute({"状态", "status"}, False, self._status, self._get_description({"状态"})),
            CommandRoute({"面板", "dashboard", "panel", "概览", "overview"}, False, self._status, self._get_description({"状态"})),
            CommandRoute({"模型", "models", "model"}, False, self._show_models, self._get_description({"模型"})),
            CommandRoute({"参考音频", "ref", "reference", "voices", "voice"}, False, self._show_voices, self._get_description({"参考音频"})),
            CommandRoute({"食物", "food", "食物菜单", "foodmenu", "菜单食物"}, False, self._food_menu, self._get_description({"食物"})),
            CommandRoute({"库存", "背包", "食物背包", "foodinv", "inventory"}, False, self._food_inventory, self._get_description({"库存"})),
            CommandRoute({"买", "购买", "buy"}, False, self._food_buy, self._get_description({"买"})),
            CommandRoute({"吃", "进食", "eat"}, False, self._food_eat, self._get_description({"吃"})),
            CommandRoute({"喝", "喝水", "drink", "water"}, False, self._drink_record, self._get_description({"喝"})),
            # /study 移除：转发后端 Aveline /studylog（记录学习日志）
            # /学习 /学 保留本地切换学习模式
            CommandRoute({"学习", "学"}, False, self._study_record, self._get_description({"学习"})),
            CommandRoute({"切模型", "switchmodel", "switch_model"}, True, self._switch_model, self._get_description({"切模型"})),
            CommandRoute({"切人设", "切换人设", "switchpersona", "switch_persona"}, True, self._switch_persona, self._get_description({"切人设"})),
            CommandRoute({"人设", "persona"}, False, self._show_personas, self._get_description({"人设"})),
            CommandRoute({"llm"}, False, self._llm, self._get_description({"llm"})),
            CommandRoute({"tts", "合成", "语音合成"}, False, self._tts, self._get_description({"tts"})),
            CommandRoute({"设置参考音频", "setref", "set_reference", "use_voice"}, False, self._set_voice, self._get_description({"设置参考音频"})),
            CommandRoute({"生图", "画", "image", "img", "作图", "绘图"}, False, self._image_gen, self._get_description({"生图"})),
            CommandRoute({"t2i"}, False, self._t2i, self._get_description({"t2i"})),
            # /save 移除：转发后端 Aveline /save（保存后端偏好）
            # /保存配置 保留本地保存 Bot 端 prefs
            CommandRoute({"保存配置"}, True, self._save_config, self._get_description({"保存配置"})),
            # /mode /模式 移除：转发后端 Aveline /mode（操作后端 PreferenceManager）
            # /学习模式 /studymode 保留本地切换学习模式
            CommandRoute({"学习模式", "study_mode", "studymode"}, False, self._study_mode, self._get_description({"学习模式"})),
            CommandRoute({"私密模式", "隐私模式", "privacy_mode", "privacymode"}, False, self._privacy_mode, self._get_description({"私密模式"})),
            # /latency 移除：转发后端 Aveline /latency（改全局 settings）
            # /仿生延迟 /perf 保留本地改 session prefs
            CommandRoute({"仿生延迟", "perf"}, True, self._latency, self._get_description({"仿生延迟"})),
            CommandRoute({"回复模式", "reply_mode", "replymode"}, True, self._reply_mode, self._get_description({"回复模式"})),
            CommandRoute({"只语音", "语音回复", "voiceonly", "voice_only"}, True, self._voice_only, self._get_description({"只语音"})),
            CommandRoute({"截图", "screen", "screenshot"}, True, self._screenshot, self._get_description({"截图"})),
            CommandRoute({"文件", "file", "fs"}, True, self._file_ops, self._get_description({"文件"})),
            CommandRoute({"批准", "approve", "confirm", "yes", "同意"}, True, self._approve, self._get_description({"批准"})),
            CommandRoute({"拒绝", "reject", "deny", "no", "不同意"}, True, self._reject, self._get_description({"拒绝"})),
            CommandRoute({"oc", "openclaw"}, False, self._openclaw, self._get_description({"oc"})),
            CommandRoute({"搜索", "搜", "search", "web"}, False, self._web_search, self._get_description({"搜索"})),
            CommandRoute({"sid", "会话id", "sessionid"}, False, self._sid, self._get_description({"sid"})),
            CommandRoute({"表情", "meme", "斗图"}, False, self._meme, self._get_description({"表情"})),
            CommandRoute({"历史", "history", "记录", "聊天记录"}, False, self._history, self._get_description({"历史"})),
            CommandRoute({"会话列表", "sessions", "sessionls", "ls"}, False, self._session_list, self._get_description({"会话列表"})),
            CommandRoute({"会话重命名", "renamesession", "sessionrename"}, True, self._session_rename, self._get_description({"会话重命名"})),
            CommandRoute({"删除会话", "delsession", "sessiondel"}, True, self._session_delete, self._get_description({"删除会话"})),
            CommandRoute({"唤醒", "叫醒", "wake", "forcewake"}, True, self._sleep_wake, self._get_description({"唤醒"})),
            CommandRoute({"打断", "interrupt", "forceinterrupt", "busywake"}, True, self._activity_interrupt, self._get_description({"打断"})),
            CommandRoute({"跳过活动", "跳过", "skipactivity", "skip"}, True, self._activity_skip, self._get_description({"跳过活动"})),
            CommandRoute({"继续聊", "延长", "extend", "extendchat"}, True, self._activity_extend, self._get_description({"继续聊"})),
            # /clear 移除：转发后端 Aveline /clear（清全部记忆）
            # /清除短期记忆 /reset 保留本地只清短期记忆
            CommandRoute({"清除短期记忆", "reset"}, False, self._clear_short_memory, self._get_description({"清除短期记忆"})),
            CommandRoute({"清除本地记忆", "清除所有记忆", "clearall", "clear_all"}, True, self._clear_all_memory, self._get_description({"清除本地记忆"})),
            CommandRoute({"调试模式", "debug"}, True, self._debug_mode, self._get_description({"调试模式"})),
            CommandRoute({"重新生成", "重生成", "regenerate", "regen"}, False, self._regenerate, self._get_description({"重新生成"})),
            CommandRoute({"断句", "split"}, False, self._split_toggle, self._get_description({"断句"})),
            CommandRoute({"tts模式", "tts模式切换", "切tts", "switchtts", "tts_switch", "语音模式"}, True, self._tts_mode, self._get_description({"tts模式"})),
        ]

    def get_command_list(self) -> list[dict]:
        """获取所有注册的指令列表（用于 /help 显示）。

        Returns:
            指令列表，每项包含：command（主要别名）、description、master_only、aliases
        """
        result = []
        seen_commands = set()  # 避免重复（如 /状态 和 /面板 都是同一个）

        for route in self._routes:
            # 取第一个别名作为主命令
            primary_alias = next(iter(route.aliases), "")
            if primary_alias in seen_commands:
                continue
            seen_commands.add(primary_alias)

            result.append({
                "command": f"/{primary_alias}",
                "description": route.description or self._get_description(route.aliases),
                "master_only": route.master_only,
                "aliases": [f"/{a}" for a in route.aliases if a != primary_alias],
            })

        return result

    async def dispatch(
        self,
        *,
        cmd_lower: str,
        session_id: str,
        msg_type: str,
        qq_user_id: str,
        group_id: str,
        rest: str,
        prefs: dict,
        is_master: bool,
    ) -> bool | None:
        route = next((r for r in self._routes if cmd_lower in r.aliases), None)
        if route is None:
            return None

        if route.master_only and not is_master:
            await self.adapter.send_to_napcat(session_id, "权限不足")
            return True

        return await route.handler(
            session_id=session_id,
            msg_type=msg_type,
            qq_user_id=qq_user_id,
            group_id=group_id,
            rest=rest,
            prefs=prefs,
            is_master=is_master,
            cmd_lower=cmd_lower,
        )

    async def _help(self, **ctx) -> bool:
        await self.adapter.system_handler.show_help(ctx["session_id"])
        return True

    async def _module_docs(self, **ctx) -> bool:
        await self.adapter.system_handler.show_module_docs(ctx["session_id"], ctx["rest"])
        return True

    async def _status(self, **ctx) -> bool:
        await self.adapter.dashboard_handler.show_status(ctx["session_id"], ctx["prefs"], ctx["is_master"], ctx["rest"])
        return True

    async def _show_models(self, **ctx) -> bool:
        await self.adapter.resource_handler.show_models(ctx["session_id"], ctx["prefs"], ctx["rest"])
        return True

    async def _show_voices(self, **ctx) -> bool:
        await self.adapter.resource_handler.show_voices(ctx["session_id"], ctx["prefs"])
        return True

    async def _food_menu(self, **ctx) -> bool:
        await self.adapter.food_handler.show_food_menu(ctx["session_id"], ctx["rest"])
        return True

    async def _food_inventory(self, **ctx) -> bool:
        await self.adapter.food_handler.show_food_inventory(ctx["session_id"])
        return True

    async def _food_buy(self, **ctx) -> bool:
        await self.adapter.food_handler.handle_food_buy(ctx["session_id"], ctx["rest"])
        return True

    async def _food_eat(self, **ctx) -> bool:
        await self.adapter.food_handler.handle_food_eat(
            ctx["session_id"],
            ctx["rest"],
            ctx["prefs"],
        )
        return True

    async def _drink_record(self, **ctx) -> bool:
        sid = ctx["session_id"]
        raw = str(ctx["rest"] or "").strip()
        amount_ml = None
        units = None
        beverage_parts = []

        if raw:
            for token in [p for p in raw.split() if p]:
                lower = token.lower()
                if amount_ml is None and lower.endswith("ml") and lower[:-2].isdigit():
                    amount_ml = int(lower[:-2])
                    continue
                if units is None:
                    try:
                        val = float(token)
                        units = val
                        continue
                    except ValueError:
                        pass
                beverage_parts.append(token)
        
        beverage_name = " ".join(beverage_parts) if beverage_parts else "水"
        final_ml = 250
        if amount_ml is not None:
            final_ml = amount_ml
        elif units is not None:
            final_ml = int(units * 250)
        
        await self.adapter.food_handler.handle_drink(sid, beverage_name, final_ml)
        return True

    async def _study_record(self, **ctx) -> bool:
        rest = str(ctx["rest"] or "").strip()
        if not rest:
            await self.adapter.send_to_napcat(ctx["session_id"], "用法：/学习 <科目> [分钟] | /学习 结束")
            return True
        if rest in {"stop", "end", "结束", "完成", "finish"}:
            await self.adapter.lifecycle_handler.end_study_mode(ctx["session_id"])
            return True
        
        # Parse "Subject Duration"
        parts = rest.split(None, 1)
        subject = parts[0]
        duration = 45
        if len(parts) > 1:
            try:
                # Handle "Subject 60" or "Subject 60 | Notes"
                maybe_dur = parts[1].split("|")[0].strip()
                if maybe_dur.isdigit():
                    duration = int(maybe_dur)
            except Exception:
                pass
        
        await self.adapter.lifecycle_handler.start_study_mode(ctx["session_id"], subject, duration)
        return True

    async def _switch_model(self, **ctx) -> bool:
        await self.adapter.resource_handler.handle_switch_model(ctx["session_id"], ctx["rest"], ctx["prefs"], ctx["qq_user_id"])
        return True

    async def _switch_persona(self, **ctx) -> bool:
        await self.adapter.resource_handler.handle_switch_persona(ctx["session_id"], ctx["rest"], ctx["prefs"], ctx["qq_user_id"])
        return True

    async def _show_personas(self, **ctx) -> bool:
        await self.adapter.resource_handler.show_personas(ctx["session_id"], ctx["prefs"])
        return True

    async def _llm(self, **ctx) -> bool:
        sid = ctx["session_id"]
        prefs = ctx["prefs"]
        arg = str(ctx["rest"] or "").strip().lower()
        
        if not arg or arg == "status":
            state = "开启" if bool(prefs.get("llm_enabled", True)) else "关闭"
            await self.adapter.send_to_napcat(sid, f"当前 LLM 聊天状态：{state}")
            return True
            
        new_state = arg in {"on", "true", "1", "开启", "开"}
        prefs["llm_enabled"] = new_state
        # Persist
        await self.adapter.config_handler.update_session_config(sid, "llm_enabled", new_state)
        
        w = "开启" if new_state else "关闭"
        await self.adapter.send_to_napcat(sid, f"已{w} LLM 聊天。")
        return True

    async def _tts(self, **ctx) -> bool:
        sid = ctx["session_id"]
        arg = str(ctx["rest"] or "").strip()
        if not arg:
            await self.adapter.send_to_napcat(sid, "用法：/tts <文本>")
            return True
        await self.adapter._send_voice_response(sid, arg)
        return True

    async def _set_voice(self, **ctx) -> bool:
        await self.adapter.resource_handler.handle_set_voice(ctx["session_id"], ctx["rest"], ctx["prefs"])
        return True

    async def _image_gen(self, **ctx) -> bool:
        await self.adapter.media_handler.handle_image_gen(ctx["session_id"], ctx["rest"])
        return True

    async def _t2i(self, **ctx) -> bool:
        sid = ctx["session_id"]
        prefs = ctx["prefs"]
        arg = str(ctx["rest"] or "").strip().lower()
        
        if not arg or arg == "status":
            state = "开启" if bool(prefs.get("t2i_mode", False)) else "关闭"
            await self.adapter.send_to_napcat(sid, f"当前文生图模式状态：{state}")
            return True
            
        new_state = arg in {"on", "true", "1", "开启", "开"}
        prefs["t2i_mode"] = new_state
        # Persist
        await self.adapter.config_handler.update_session_config(sid, "t2i_mode", new_state)
        
        w = "开启" if new_state else "关闭"
        await self.adapter.send_to_napcat(sid, f"已{w}文生图模式。")
        return True

    async def _save_config(self, **ctx) -> bool:
        await self.adapter.config_handler.persist_user_override(ctx["qq_user_id"], ctx["prefs"])
        await self.adapter.send_to_napcat(ctx["session_id"], "当前偏好配置已保存。")
        return True

    async def _study_mode(self, **ctx) -> bool:
        return await handle_study_mode(self, **ctx)

    async def _privacy_mode(self, **ctx) -> bool:
        return await handle_privacy_mode(self, **ctx)

    async def _latency(self, **ctx) -> bool:
        return await handle_latency(self, **ctx)

    async def _reply_mode(self, **ctx) -> bool:
        return await handle_reply_mode(self, **ctx)

    async def _voice_only(self, **ctx) -> bool:
        return await handle_voice_only(self, **ctx)

    async def _screenshot(self, **ctx) -> bool:
        await self.adapter.system_handler.handle_remote_screenshot(ctx["session_id"], ctx["rest"])
        return True

    async def _file_ops(self, **ctx) -> bool:
        await self.adapter.system_handler.handle_remote_file(ctx["session_id"], ctx["rest"])
        return True

    async def _approve(self, **ctx) -> bool:
        await self.adapter.system_handler.handle_approval(ctx["session_id"], ctx["rest"], is_reject=False)
        return True

    async def _reject(self, **ctx) -> bool:
        await self.adapter.system_handler.handle_approval(ctx["session_id"], ctx["rest"], is_reject=True)
        return True

    async def _openclaw(self, **ctx) -> bool:
        return await handle_openclaw(self, **ctx)

    async def _web_search(self, **ctx) -> bool:
        return await handle_web_search(self, **ctx)

    async def _sid(self, **ctx) -> bool:
        return await handle_sid(self, **ctx)

    async def _meme(self, **ctx) -> bool:
        return await handle_meme(self, **ctx)

    async def _history(self, **ctx) -> bool:
        return await handle_history(self, **ctx)

    async def _session_list(self, **ctx) -> bool:
        return await handle_session_list(self, **ctx)

    async def _session_rename(self, **ctx) -> bool:
        return await handle_session_rename(self, **ctx)

    async def _session_delete(self, **ctx) -> bool:
        return await handle_session_delete(self, **ctx)

    async def _sleep_wake(self, **ctx) -> bool:
        return await handle_sleep_wake(self, **ctx)

    async def _activity_interrupt(self, **ctx) -> bool:
        return await handle_activity_interrupt(self, **ctx)

    async def _activity_skip(self, **ctx) -> bool:
        return await handle_activity_skip(self, **ctx)

    async def _activity_extend(self, **ctx) -> bool:
        return await handle_activity_extend(self, **ctx)

    async def _clear_short_memory(self, **ctx) -> bool:
        return await handle_clear_short_memory(self, **ctx)

    async def _clear_all_memory(self, **ctx) -> bool:
        return await handle_clear_all_memory(self, **ctx)

    async def _debug_mode(self, **ctx) -> bool:
        return await handle_debug_mode(self, **ctx)

    async def _regenerate(self, **ctx) -> bool:
        return await handle_regenerate(self, **ctx)

    async def _split_toggle(self, **ctx) -> bool:
        return await handle_split_toggle(self, **ctx)

    async def _tts_mode(self, **ctx) -> bool:
        return await handle_tts_mode(self, **ctx)
