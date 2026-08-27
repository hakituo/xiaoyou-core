import asyncio
import os
import re
import time
from typing import Any, Dict, List

from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.utils import _truncate_text, _build_cq_image
from clients.bots.qq.settings import (
    BOTS_DIR,
    REMOTE_SCREENSHOT_COOLDOWN_SECONDS,
    REMOTE_SCREENSHOT_ENABLED,
    REMOTE_FILE_OPS_ENABLED,
    _HAS_STATUS_RENDERER,
    generate_help_image,
)

class SystemHandler(BaseHandler):
    """
    Handles system-level commands like help, documentation, and configuration.
    """

    async def show_help(self, session_id: str):
        """Displays the help menu.

        P1-7: 动态合并两份命令清单：
        1. 后端服务端命令（通过 /api/v1/system/commands 实时获取）
        2. 本地 Bot 端命令（从 CommandRouter.get_command_list 获取）
        后端命令变更后前端自动同步，无需手动维护两份清单。
        """
        # 1. 获取本地 Bot 端命令
        if hasattr(self.adapter, "command_router"):
            bot_commands = self.adapter.command_router.get_command_list()
        else:
            bot_commands = self._get_fallback_commands()

        # 2. 从后端 API 获取服务端命令（带 2s 超时，失败则降级）
        server_commands = await self._fetch_server_commands()

        # 3. 合并两份清单
        all_commands = self._merge_commands(server_commands, bot_commands)

        if _HAS_STATUS_RENDERER and callable(generate_help_image):
            img_path = generate_help_image(all_commands)
            if img_path and os.path.exists(img_path):
                await self.adapter.send_to_napcat(session_id, _build_cq_image(img_path))
                return

        # 文本模式：按 category 分组渲染
        lines = self._render_help_text(all_commands)
        await self.adapter.send_to_napcat(session_id, _truncate_text("\n".join(lines), 1800))

    async def _fetch_server_commands(self) -> list[dict]:
        """从后端 /api/v1/system/commands 获取服务端命令清单。

        失败时返回空列表（降级为仅显示 Bot 端命令）。
        """
        try:
            import aiohttp

            # 从 adapter.cfg 获取后端地址，兼容不同 adapter 实现
            cfg = getattr(self.adapter, "cfg", None)
            base_url = ""
            if cfg is not None:
                base_url = getattr(cfg, "xiaoyou_http_base_url", "") or ""
            if not base_url:
                base_url = "http://127.0.0.1:8000"

            url = f"{base_url.rstrip('/')}/api/v1/system/commands"
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    # 兼容 success_response 包装
                    if isinstance(data, dict) and "data" in data:
                        return data["data"].get("commands", []) or []
                    return data.get("commands", []) or []
        except Exception:
            return []

    @staticmethod
    def _merge_commands(server_cmds: list[dict], bot_cmds: list[dict]) -> list[dict]:
        """合并服务端与 Bot 端命令，去重（以 command 名为准）。"""
        seen = set()
        merged: list[dict] = []

        # 服务端命令在前
        for c in server_cmds:
            cmd_key = (c.get("command") or "").lstrip("/")
            if cmd_key and cmd_key not in seen:
                seen.add(cmd_key)
                c.setdefault("category", "对话命令")
                c.setdefault("source", "aveline_backend")
                merged.append(c)
                # 同时将别名加入 seen 避免重复
                for a in c.get("aliases", []):
                    seen.add(a.lstrip("/"))

        # Bot 端命令在后
        for c in bot_cmds:
            cmd_key = (c.get("command") or "").lstrip("/")
            if cmd_key and cmd_key not in seen:
                seen.add(cmd_key)
                c.setdefault("category", "Bot命令")
                c.setdefault("source", "bot_client")
                merged.append(c)
                for a in c.get("aliases", []):
                    seen.add(a.lstrip("/"))

        return merged

    @staticmethod
    def _render_help_text(commands: list[dict]) -> list[str]:
        """按 category 分组渲染帮助文本。

        P1-7: 收口后 Bot 端命令和后端命令不再冲突，
        按来源分组展示：后端命令（Aveline）在前，本地命令（Bot）在后。
        """
        from collections import defaultdict

        # 按来源分两大类，再按 category 细分
        backend_cmds = [c for c in commands if c.get("source") == "aveline_backend"]
        bot_cmds = [c for c in commands if c.get("source") == "bot_client"]

        lines = ["可用指令："]

        if backend_cmds:
            lines.append("\n【对话命令】（后端处理）")
            for c in backend_cmds:
                cmd = c.get("command", "")
                desc = c.get("description", "")
                master = " [Master]" if c.get("master_only") else ""
                lines.append(f"{cmd}{master} - {desc}")

        if bot_cmds:
            # 本地命令按 category 分组
            groups: dict[str, list[dict]] = defaultdict(list)
            for c in bot_cmds:
                groups[c.get("category", "Bot命令")].append(c)
            for category, cmds in groups.items():
                lines.append(f"\n【{category}】（本地处理）")
                for c in cmds:
                    cmd = c.get("command", "")
                    desc = c.get("description", "")
                    master = " [Master]" if c.get("master_only") else ""
                    lines.append(f"{cmd}{master} - {desc}")

        return lines

    def _get_fallback_commands(self) -> list[dict]:
        """回退的硬编码指令列表（当 CommandRouter 不可用时）。"""
        return [
            {"command": "/模块", "description": "查看功能模块介绍"},
            {"command": "/状态", "description": "总面板概览"},
            {"command": "/模型", "description": "查看可用模型列表"},
            {"command": "/help", "description": "指令速查菜单"},
        ]

    async def handle_remote_screenshot(self, session_id: str, rest: str = ""):
        if not REMOTE_SCREENSHOT_ENABLED:
            await self.adapter.send_to_napcat(
                session_id,
                "远程截图未开启。请在 clients/bots/config.json 设置 remote_screenshot_enabled=true。",
            )
            return
        now = time.time()
        last_ts = float(getattr(self, "_last_screenshot_ts", 0.0) or 0.0)
        cooldown = max(1.0, float(REMOTE_SCREENSHOT_COOLDOWN_SECONDS))
        left = cooldown - (now - last_ts)
        if left > 0:
            await self.adapter.send_to_napcat(
                session_id,
                f"截图请求过于频繁，请 {left:.1f}s 后重试。",
            )
            return
        try:
            image_path = await asyncio.to_thread(self._capture_screenshot_sync)
        except Exception as e:
            await self.adapter.send_to_napcat(
                session_id, f"截图失败：{str(e) or type(e).__name__}"
            )
            return
        self._last_screenshot_ts = now
        await self.adapter.send_to_napcat(
            session_id, f"已执行截图（{time.strftime('%H:%M:%S')}）。"
        )
        await self.adapter.send_to_napcat(session_id, _build_cq_image(image_path))

    async def handle_remote_file(self, session_id: str, rest: str = ""):
        if not REMOTE_FILE_OPS_ENABLED:
            await self.adapter.send_to_napcat(
                session_id,
                "远程文件操作未开启。请在 clients/bots/config.json 设置 remote_file_ops_enabled=true。",
            )
            return
        raw = str(rest or "").strip()
        if not raw:
            await self.adapter.send_to_napcat(
                session_id,
                "用法：/文件 列表 [路径] | /文件 读 <路径> | /文件 写 <路径> | <内容> | /文件 追加 <路径> | <内容> | /文件 建目录 <路径> | /文件 存在 <路径>",
            )
            return
        parts = raw.split(None, 1)
        op = str(parts[0] or "").strip().lower()
        payload = str(parts[1] or "").strip() if len(parts) > 1 else ""
        op_map = {
            "列表": "list",
            "ls": "list",
            "list": "list",
            "读": "read",
            "读取": "read",
            "read": "read",
            "写": "write",
            "写入": "write",
            "write": "write",
            "追加": "append",
            "append": "append",
            "建目录": "mkdir",
            "mkdir": "mkdir",
            "存在": "exists",
            "exists": "exists",
        }
        action = op_map.get(op)
        if not action:
            await self.adapter.send_to_napcat(session_id, f"不支持的文件动作：{op}")
            return
        body: Dict[str, Any] = {"action": action}
        if action == "list":
            body["path"] = payload or "."
            body["limit"] = 200
        elif action == "read":
            if not payload:
                await self.adapter.send_to_napcat(session_id, "读取文件需要路径：/文件 读 <路径>")
                return
            body["path"] = payload
            body["max_chars"] = 200000
        elif action in {"write", "append"}:
            left, sep, right = payload.partition("|")
            file_path = left.strip()
            file_content = right if sep else ""
            if not file_path or not sep:
                await self.adapter.send_to_napcat(
                    session_id, "写入格式：/文件 写 <路径> | <内容>（追加同理）"
                )
                return
            body["path"] = file_path
            body["content"] = file_content
        else:
            if not payload:
                await self.adapter.send_to_napcat(session_id, f"{op} 需要路径：/文件 {op} <路径>")
                return
            body["path"] = payload
        status, data = await self.api_request(
            "POST", "/api/v1/admin/remote/file/action", json_body=body
        )
        if status != 200 or not isinstance(data, dict):
            await self.adapter.send_to_napcat(session_id, f"远程文件操作失败（HTTP {status}）")
            return
        if not bool(data.get("success", False)):
            message = str(data.get("message") or data.get("error") or "远程文件操作失败")
            await self.adapter.send_to_napcat(session_id, message)
            return
        payload_data = data.get("data") if isinstance(data.get("data"), dict) else {}

        if action == "list":
            items = payload_data.get("items") if isinstance(payload_data.get("items"), list) else []
            lines = [f"目录：{payload_data.get('current') or '.'}（最多显示30项）"]
            for item in items[:30]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "")
                marker = "📁" if bool(item.get("is_dir")) else "📄"
                lines.append(f"{marker} {name}")
            if len(items) > 30:
                lines.append(f"... 其余 {len(items) - 30} 项省略")
            await self.adapter.send_to_napcat(session_id, _truncate_text("\n".join(lines), 1800))
            return
        if action == "read":
            content = str(payload_data.get("content") or "")
            path = str(payload_data.get("path") or body.get("path") or "")
            text = f"文件：{path}\n\n{content}"
            await self.adapter.send_to_napcat(session_id, _truncate_text(text, 1800))
            return
        await self.adapter.send_to_napcat(
            session_id,
            f"远程文件操作完成：{action} {str(payload_data.get('path') or body.get('path') or '').strip()}",
        )

    async def handle_approval(self, session_id: str, rest: str, is_reject: bool = False):
        token = str(rest or "").strip()
        if not token:
            op = "拒绝" if is_reject else "批准"
            await self.adapter.send_to_napcat(session_id, f"请输入审批 Token：/{op} <Token>")
            return
        
        endpoint = "/api/v1/admin/remote/reject" if is_reject else "/api/v1/admin/remote/approve"
        status, data = await self.api_request(
            "POST", endpoint, json_body={"token": token}
        )
        if status != 200 or not isinstance(data, dict):
            await self.adapter.send_to_napcat(session_id, f"审批操作失败（HTTP {status}）")
            return
        
        msg = str(data.get("message") or data.get("error") or "操作完成")
        
        # If execution returned a result
        inner_data = data.get("data")
        if isinstance(inner_data, dict):
             if inner_data.get("message"):
                 msg = inner_data.get("message")
             if inner_data.get("result"):
                 # If the file operation returned data, show it
                 res = inner_data.get("result")
                 if isinstance(res, dict) and res.get("action"):
                     msg += f"\n执行结果: {res.get('action')} 成功"
        
        await self.adapter.send_to_napcat(session_id, msg)

    async def show_module_docs(self, session_id: str, rest: str):
        """Displays documentation for specific modules."""
        arg = str(rest or "").strip()
        if not arg or arg.lower() in {"list", "列表"}:
            mods = self._get_module_docs()
            lines = [
                "【功能模块说明】",
                "用法：/模块 <模块名>  |  /模块 列表",
                "示例：/模块 记忆  |  /模块 语音  |  /模块 状态",
                "",
                "可用模块：",
            ]
            for mod in mods:
                k = str(mod.get("key") or "").strip()
                title = str(mod.get("title") or "").strip()
                if k and title:
                    lines.append(f"- {k}：{title}")
                elif k:
                    lines.append(f"- {k}")
            await self.adapter.send_to_napcat(session_id, _truncate_text("\n".join(lines), 3500))
            return

        matches = self._match_module_docs(arg)
        if not matches:
            await self.adapter.send_to_napcat(session_id, f"未找到模块：{arg}。发送 /模块 列表 查看可用模块。")
            return

        if len(matches) > 1:
            lines = [f"找到多个可能的模块（关键词：{arg}）："]
            for mod in matches[:12]:
                k = str(mod.get("key") or "").strip()
                title = str(mod.get("title") or "").strip()
                if k and title:
                    lines.append(f"- {k}：{title}")
                elif k:
                    lines.append(f"- {k}")
            lines.append("发送 /模块 <模块名> 查看详情。")
            await self.adapter.send_to_napcat(session_id, _truncate_text("\n".join(lines), 2500))
            return

        doc = self._render_module_doc(matches[0])
        await self.adapter.send_to_napcat(session_id, doc)

    def _get_module_docs(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "上手",
                "aliases": ["start", "入门", "简介", "overview", "总览"],
                "title": "上手与交互方式",
                "summary": "QQ 端有两种使用方式：① 直接聊天（会走小友核心对话链路）；② 发送 / 开头的指令（用于控制/查看系统能力）。",
                "commands": [
                    ("/help", "指令速查菜单"),
                    ("/模块", "按模块查看功能说明"),
                    ("/模块 <模块名>", "查看指定模块的详细说明与示例"),
                ],
                "examples": [
                    "直接发：你好呀（进入正常对话）",
                    "发：/模块 记忆（查看记忆模块怎么用）",
                ],
            },
            {
                "key": "状态",
                "aliases": ["面板", "dashboard", "panel", "status", "系统状态"],
                "title": "状态与面板",
                "summary": "用于查看小友核心的运行情况、资源占用、服务健康、情绪/生物状态等。适合排查“为什么变慢/不回复/模型没加载”。",
                "commands": [
                    ("/状态", "总面板概览（别名 /面板）"),
                    ("/状态 资源", "CPU/内存/GPU 等资源详情"),
                    ("/状态 服务", "服务健康状态"),
                    ("/状态 模块", "模型/语音等模块统计"),
                    ("/状态 记忆", "记忆统计与分类分布"),
                    ("/状态 情绪", "当前情绪与分布"),
                    ("/状态 生物", "生命体征/免疫/神经递质等"),
                ],
                "examples": [
                    "发：/状态 资源（看看 GPU 是否满了）",
                    "发：/状态 服务（看看哪个服务掉线）",
                ],
            },
            {
                "key": "模型",
                "aliases": ["llm", "models", "model", "切模型", "生图模型"],
                "title": "模型管理（聊天/生图）",
                "summary": "用于查看与切换当前聊天模型（LLM）/生图模型。切换通常需要 Master 权限，避免群里被乱切导致体验波动。",
                "commands": [
                    ("/模型", "列出可用模型（含 LLM 与生图模型）"),
                    ("/切模型 <名称/ID>", "切换聊天模型或生图模型（Master）"),
                ],
                "examples": [
                    "发：/模型（先看有哪些模型）",
                    "发：/切模型 deepseek-v3（切换聊天模型）",
                ],
            },
            {
                "key": "人设",
                "aliases": ["persona", "性格", "角色", "切人设"],
                "title": "人设与语气",
                "summary": "人设决定小友的说话风格、行为边界与一些偏好。切换人设会影响后续对话的语气与输出风格。",
                "commands": [
                    ("/人设", "列出可用人设"),
                    ("/切人设 <名称/序号/filename>", "切换当前人设（Master）"),
                ],
                "examples": [
                    "发：/人设（查看列表）",
                    "发：/切人设 2（用序号切换）",
                ],
            },
            {
                "key": "语音",
                "aliases": ["tts", "声音", "语音合成", "参考音频", "voices", "voice"],
                "title": "语音（TTS）与参考音频",
                "summary": "用于把文本合成为语音，并支持选择参考音频来改变音色/说话风格。",
                "commands": [
                    ("/参考音频", "列出可用参考音频"),
                    ("/设置参考音频 <路径/序号>", "设置当前会话使用的参考音频"),
                    ("/tts <文本>", "把文本合成为语音并发送"),
                ],
                "examples": [
                    "发：/参考音频（先找一个合适的音色）",
                    "发：/设置参考音频 1（用序号选择）",
                    "发：/tts 晚安，我先去休息啦（合成语音）",
                ],
            },
            {
                "key": "生图",
                "aliases": ["画", "image", "img", "图片", "生成图片"],
                "title": "生图（图片生成）",
                "summary": "使用当前生图模型根据提示词生成图片。适合做头像、场景图、灵感草图等。",
                "commands": [
                    ("/生图 <提示词>", "生成图片"),
                    ("/切模型 <名称/ID>", "切换生图模型（Master）"),
                ],
                "examples": [
                    "发：/生图 赛博朋克风格的猫咪头像，霓虹灯，高清（生成一张图）",
                ],
            },
            {
                "key": "记忆",
                "aliases": ["memory", "清除", "reset", "聊天记录"],
                "title": "记忆与会话清理",
                "summary": "用于清理当前对话上下文，或（Master）彻底删除本地历史记忆。遇到“说着说着跑偏/被旧话题带跑”时很有用。",
                "commands": [
                    ("/清除短期记忆", "清理当前上下文记忆（别名 /clear /reset）"),
                    ("/清除本地记忆", "彻底删除本地所有历史记忆（Master）"),
                ],
                "examples": [
                    "发：/清除短期记忆（让对话重新开始）",
                ],
            },
            {
                "key": "食物",
                "aliases": ["food", "背包", "库存", "buy", "eat"],
                "title": "食物系统（投喂/背包/购买）",
                "summary": "这是生活模拟的一部分：你可以查看食物菜单、购买进背包、再投喂让小友进食，从而影响状态与反馈。",
                "commands": [
                    ("/食物", "查看食物菜单（可带关键词过滤）"),
                    ("/库存", "查看背包与过期时间"),
                    ("/买 <序号/ID> [数量]", "购买食物（支持 19*10 或 19 10）"),
                    ("/吃 <序号/ID>", "进食（优先消耗背包）"),
                ],
                "examples": [
                    "发：/食物 奶茶（筛选菜单）",
                    "发：/买 1 2（买第 1 个食物 2 份）",
                    "发：/买 19*10（买第 19 个食物 10 份）",
                    "发：/库存（看看背包里有什么）",
                    "发：/吃 1（投喂/进食）",
                    "发：/喝 1（快速记录 250ml 喝水）",
                ],
            },
            {
                "key": "学习打卡",
                "aliases": ["学习", "study", "专注", "低打扰"],
                "title": "学习记录与低打扰模式",
                "summary": "用于一键记录学习科目与时长，并自动进入低打扰模式；学习结束后可一键恢复普通模式。",
                "commands": [
                    ("/学习 <科目> [分钟]", "记录学习并进入低打扰模式"),
                    ("/学习 结束", "结束学习低打扰并恢复普通模式"),
                    ("/学习模式 on/off/status", "快速切换学习模式（study/normal）"),
                    ("/私密模式 on/off/status", "快速切换私密模式（privacy/normal）"),
                    ("/模式 <study|normal|privacy|entertainment>", "切换完整偏好模式"),
                ],
                "examples": [
                    "发：/学习 线代 90",
                    "发：/学习 英语 45 | 背了30个单词",
                    "发：/学习 结束",
                    "发：/私密模式 on（进入隐私对话）",
                ],
            },
            {
                "key": "群聊",
                "aliases": ["回复模式", "at", "all", "群"],
                "title": "群聊回复模式",
                "summary": "控制在群聊里小友是“只在被艾特时回复”还是“看到就回”。为了避免刷屏，默认通常是仅艾特。",
                "commands": [
                    ("/回复模式 at", "仅艾特时回复（Master）"),
                    ("/回复模式 all", "群内全部消息都回复（Master）"),
                ],
                "examples": [
                    "发：/回复模式 at（避免群里刷屏）",
                    "发：/回复模式 all（小范围测试再开）",
                ],
            },
            {
                "key": "调试",
                "aliases": ["debug", "调试模式", "保存配置", "latency", "perf", "仿生延迟"],
                "title": "调试/性能/配置",
                "summary": "偏运维与体验调优：无状态调试模式（不保存历史）、仿生延迟开关、保存当前偏好等。大多需要 Master 权限。",
                "commands": [
                    ("/调试模式", "切换无状态模式（不保存历史，Master）"),
                    ("/仿生延迟 on/off", "切换仿生学认知延迟（Master）"),
                    ("/保存配置", "保存当前会话偏好（Master）"),
                ],
                "examples": [
                    "发：/调试模式（临时测试，不污染历史）",
                    "发：/仿生延迟 off（追求更快首 token）",
                ],
            },
            {
                "key": "OpenClaw",
                "aliases": ["oc", "openclaw", "任务执行", "工具执行"],
                "title": "OpenClaw 任务执行（路由+执行层）",
                "summary": "把复杂任务交给 OpenClaw 执行，再将执行结果回传到 QQ。适合自动化、检索、总结、跨步骤任务。",
                "commands": [
                    ("/oc <任务描述>", "执行任务并返回结果"),
                    ("/oc 状态", "查看 OpenClaw 地址、模型、鉴权和连通"),
                    ("/oc 模型 [ID]", "查看或设置当前会话使用模型"),
                    ("/oc 模型列表", "拉取 OpenClaw 网关可用模型"),
                    ("/搜索 <关键词>", "直接执行联网搜索并输出结论+来源"),
                ],
                "examples": [
                    "发：/oc 帮我总结今天仓库变更并给出风险点",
                    "发：/oc 状态（确认网关是否可用）",
                    "发：/oc 模型 anthropic/claude-opus-4-1",
                    "发：/oc 模型列表（挑一个可用模型）",
                    "发：/搜索 今天半导体板块收盘情况",
                ],
            },
            {
                "key": "远程执行",
                "aliases": ["截图", "screen", "screenshot", "远程"],
                "title": "远程操作（安全模式）",
                "summary": "当前已开放受控截图与学习文件操作能力，仅 Master 可用。学习文件写入默认直接执行。",
                "commands": [
                    ("/截图", "抓取当前机器屏幕并回传"),
                    ("/文件 列表 [路径]", "列出 Study 目录文件"),
                    ("/文件 读 <路径>", "读取 Study 文件"),
                    ("/文件 写 <路径> | <内容>", "覆盖写入 Study 文件"),
                    ("/文件 追加 <路径> | <内容>", "追加写入 Study 文件"),
                ],
                "examples": [
                    "发：/截图（查看当前桌面状态）",
                    "发：/文件 列表 .",
                    "发：/文件 写 test.txt | hello",
                ],
            },
        ]

    def _capture_screenshot_sync(self) -> str:
        from PIL import ImageGrab

        temp_dir = os.path.join(BOTS_DIR, "temp_images")
        try:
            if hasattr(self.adapter, "lifecycle_handler") and self.adapter.lifecycle_handler:
                temp_dir = self.adapter.lifecycle_handler.get_temp_images_dir()
        except Exception:
            pass
        os.makedirs(temp_dir, exist_ok=True)
        file_name = f"remote_screen_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.png"
        file_path = os.path.join(temp_dir, file_name)
        image = ImageGrab.grab(all_screens=True)
        image.save(file_path, format="PNG")
        return file_path

    def _render_module_doc(self, mod: Dict[str, Any]) -> str:
        title = str(mod.get("title") or "").strip() or str(mod.get("key") or "")
        summary = str(mod.get("summary") or "").strip()
        commands = mod.get("commands") if isinstance(mod.get("commands"), list) else []
        examples = mod.get("examples") if isinstance(mod.get("examples"), list) else []

        lines: list[str] = [f"【{title}】"]
        if summary:
            lines.append(summary)
        if commands:
            lines.append("")
            lines.append("主要指令：")
            for cmd, desc in commands:
                c = str(cmd or "").strip()
                d = str(desc or "").strip()
                if c and d:
                    lines.append(f"- {c}：{d}")
                elif c:
                    lines.append(f"- {c}")
        if examples:
            lines.append("")
            lines.append("常见用法：")
            for it in examples[:8]:
                s = str(it or "").strip()
                if s:
                    lines.append(f"- {s}")
        return _truncate_text("\n".join(lines), 5000)

    def _normalize_doc_query(self, s: str) -> str:
        t = str(s or "").strip().lower()
        t = re.sub(r"\s+", "", t)
        return t

    def _match_module_docs(self, query: str) -> List[Dict[str, Any]]:
        q = self._normalize_doc_query(query)
        if not q:
            return []
        out: list[dict[str, Any]] = []
        for mod in self._get_module_docs():
            key = self._normalize_doc_query(mod.get("key") or "")
            aliases = mod.get("aliases") if isinstance(mod.get("aliases"), list) else []
            alias_norm = [self._normalize_doc_query(a) for a in aliases]
            if q == key or q in alias_norm:
                return [mod]
            if q and (q in key or any(q in a for a in alias_norm)):
                out.append(mod)
        return out
