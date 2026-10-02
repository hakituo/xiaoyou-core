import asyncio
import json
from typing import Any

from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.settings import (
    OPENCLAW_API_KEY,
    OPENCLAW_ENABLED,
    OPENCLAW_HTTP_BASE_URL,
    OPENCLAW_MODEL,
    OPENCLAW_RETRY_ATTEMPTS,
    OPENCLAW_RETRY_BASE_DELAY_SECONDS,
    OPENCLAW_TIMEOUT_SECONDS,
    logger,
)
from clients.bots.qq.utils import _truncate_text


class OpenClawHandler(BaseHandler):
    """Bridge task execution to OpenClaw and return result to QQ."""

    async def show_help(self, session_id: str) -> None:
        lines = [
            "【OpenClaw 任务模式】",
            "用法：",
            "/oc <任务描述>  -> 交给 OpenClaw 执行并回报结果",
            "/oc 状态        -> 查看 OpenClaw 连通状态",
            "/oc 模型 [ID]   -> 查看/设置当前会话使用的模型",
            "/oc 模型列表     -> 查看 OpenClaw 可用模型",
            "/搜索 <关键词>   -> 走 OpenClaw 联网搜索并总结",
            "",
            "示例：",
            "/oc 帮我总结今天 Git 提交并列出风险点",
            "/oc 去网页查一下今天的美股收盘",
            "/oc 模型 anthropic/claude-opus-4-1",
            "/搜索 今天 NVIDIA 财报重点",
        ]
        await self.send_text(session_id, "\n".join(lines))

    async def show_status(self, session_id: str, prefs: dict) -> None:
        enabled = bool(OPENCLAW_ENABLED)
        model = str(prefs.get("openclaw_model") or OPENCLAW_MODEL or "").strip()
        lines = [
            "【OpenClaw 状态】",
            f"启用: {'是' if enabled else '否'}",
            f"地址: {OPENCLAW_HTTP_BASE_URL}",
            f"模型: {model or '(未设置)'}",
            f"鉴权: {'已配置' if OPENCLAW_API_KEY else '未配置'}",
        ]

        if not enabled:
            lines.append("提示: 在 clients/bots/config.json 中设置 openclaw_enabled=true")
            await self.send_text(session_id, "\n".join(lines))
            return

        ok, detail = await self._ping_openclaw()
        lines.append(f"连通: {'正常' if ok else '失败'}")
        if detail:
            lines.append(f"详情: {detail}")
        await self.send_text(session_id, _truncate_text("\n".join(lines), 1800))

    async def set_or_show_model(self, session_id: str, prefs: dict, model_arg: str) -> None:
        model_arg = str(model_arg or "").strip()
        if not model_arg:
            cur = str(prefs.get("openclaw_model") or OPENCLAW_MODEL or "").strip()
            await self.send_text(session_id, f"当前 OpenClaw 模型: {cur or '(未设置)'}")
            return
        prefs["openclaw_model"] = model_arg
        await self.send_text(session_id, f"已设置当前会话 OpenClaw 模型: {model_arg}")

    async def show_models(self, session_id: str) -> None:
        if not OPENCLAW_ENABLED:
            await self.send_text(
                session_id,
                "OpenClaw 未启用。请在 clients/bots/config.json 设置 openclaw_enabled=true 后重试。",
            )
            return

        base = str(OPENCLAW_HTTP_BASE_URL or "").rstrip("/")
        if not base:
            await self.send_text(session_id, "openclaw_http_base_url 为空")
            return

        session = await self.adapter._get_http_session()
        headers = self._auth_headers()
        try:
            async with session.get(
                f"{base}/v1/models",
                headers=headers,
                timeout=self._build_timeout(10),
            ) as resp:
                data = await self._read_json_or_text(resp)
                if resp.status != 200:
                    await self.send_text(session_id, self._format_error(resp.status, data))
                    return
                items = data.get("data") if isinstance(data, dict) else None
                if not isinstance(items, list) or not items:
                    await self.send_text(session_id, "未读取到可用模型列表")
                    return
                names = []
                for it in items:
                    if isinstance(it, dict):
                        mid = str(it.get("id") or "").strip()
                        if mid:
                            names.append(mid)
                if not names:
                    await self.send_text(session_id, "未读取到可用模型列表")
                    return
                lines = ["【OpenClaw 模型列表】"]
                lines.extend(f"{i + 1}. {name}" for i, name in enumerate(names[:40]))
                if len(names) > 40:
                    lines.append(f"... 共 {len(names)} 个模型")
                lines.append("可用：/oc 模型 <模型ID> 设置当前会话模型")
                await self.send_text(session_id, _truncate_text("\n".join(lines), 3200))
        except Exception as e:
            await self.send_text(session_id, f"读取 OpenClaw 模型列表失败: {str(e) or type(e).__name__}")

    async def handle_web_search(self, session_id: str, query: str, prefs: dict) -> None:
        query = str(query or "").strip()
        if not query:
            await self.send_text(session_id, "用法: /搜索 <关键词>")
            return
        task = (
            "请执行联网搜索并给出结构化结论。\n"
            f"查询: {query}\n"
            "输出要求:\n"
            "1) 先给3-5条关键结论\n"
            "2) 再给关键信息来源（标题+链接）\n"
            "3) 最后给风险与不确定性说明"
        )
        await self.handle_task(session_id, task, prefs)

    async def handle_task(self, session_id: str, task_text: str, prefs: dict) -> None:
        task_text = str(task_text or "").strip()
        if not task_text:
            await self.show_help(session_id)
            return

        if not OPENCLAW_ENABLED:
            await self.send_text(
                session_id,
                "OpenClaw 未启用。请在 clients/bots/config.json 设置 openclaw_enabled=true 后重试。",
            )
            return

        model = str(prefs.get("openclaw_model") or OPENCLAW_MODEL or "").strip()
        if not model:
            await self.send_text(
                session_id,
                "OpenClaw 模型未配置。请先设置 openclaw_model，或发送 /oc 模型 <模型ID>。",
            )
            return

        await self.send_text(session_id, "收到，正在调用 OpenClaw 执行任务...")
        ok, output = await self._run_openclaw(task_text, model)
        if ok:
            msg = _truncate_text(f"【OpenClaw 执行结果】\n{output}", 2800)
            await self.send_text(session_id, msg)
            return
        await self.send_friendly_error(session_id, "OpenClaw 任务执行", output)

    async def _ping_openclaw(self) -> tuple[bool, str]:
        base = str(OPENCLAW_HTTP_BASE_URL or "").rstrip("/")
        if not base:
            return False, "openclaw_http_base_url 为空"
        session = await self.adapter._get_http_session()
        headers = self._auth_headers()
        try:
            async with session.get(
                f"{base}/health",
                headers=headers,
                timeout=self._build_timeout(4.0),
            ) as resp:
                text = (await resp.text()).strip()
                if resp.status == 200:
                    return True, "health=200"
                if text:
                    return False, f"health={resp.status} {text[:160]}"
                return False, f"health={resp.status}"
        except Exception as e:
            return False, str(e) or type(e).__name__

    async def _run_openclaw(self, task_text: str, model: str) -> tuple[bool, str]:
        base = str(OPENCLAW_HTTP_BASE_URL or "").rstrip("/")
        if not base:
            return False, "openclaw_http_base_url 为空"
        session = await self.adapter._get_http_session()
        headers = self._auth_headers()

        responses_url = f"{base}/v1/responses"
        body = {"model": model, "input": task_text}

        max_attempts = max(1, int(OPENCLAW_RETRY_ATTEMPTS) + 1)
        delay_base = max(0.05, float(OPENCLAW_RETRY_BASE_DELAY_SECONDS))
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            try:
                async with session.post(
                    responses_url,
                    json=body,
                    headers=headers,
                    timeout=self._build_timeout(OPENCLAW_TIMEOUT_SECONDS),
                ) as resp:
                    data = await self._read_json_or_text(resp)
                    if resp.status == 200:
                        text = self._extract_responses_text(data)
                        if text:
                            return True, text
                        return True, json.dumps(data, ensure_ascii=False)[:2200]

                    if resp.status in {404, 405}:
                        return await self._run_openclaw_chat_completions(task_text, model)

                    err = self._format_error(resp.status, data)
                    last_error = err
                    if not self._should_retry_status(resp.status) or attempt >= max_attempts:
                        return False, err

                    wait_s = delay_base * (2 ** (attempt - 1))
                    logger.warning(
                        f"OpenClaw responses retry {attempt}/{max_attempts - 1}, status={resp.status}, wait={wait_s:.2f}s"
                    )
                    await asyncio.sleep(wait_s)
            except Exception as e:
                last_error = str(e) or type(e).__name__
                logger.error(f"OpenClaw responses API failed: {last_error}")
                if attempt >= max_attempts:
                    break
                wait_s = delay_base * (2 ** (attempt - 1))
                logger.warning(
                    f"OpenClaw responses retry {attempt}/{max_attempts - 1}, exception={type(e).__name__}, wait={wait_s:.2f}s"
                )
                await asyncio.sleep(wait_s)
        return False, last_error or "OpenClaw 请求失败"

    async def _run_openclaw_chat_completions(self, task_text: str, model: str) -> tuple[bool, str]:
        base = str(OPENCLAW_HTTP_BASE_URL or "").rstrip("/")
        session = await self.adapter._get_http_session()
        headers = self._auth_headers()
        url = f"{base}/v1/chat/completions"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": task_text}],
        }
        max_attempts = max(1, int(OPENCLAW_RETRY_ATTEMPTS) + 1)
        delay_base = max(0.05, float(OPENCLAW_RETRY_BASE_DELAY_SECONDS))
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                async with session.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=self._build_timeout(OPENCLAW_TIMEOUT_SECONDS),
                ) as resp:
                    data = await self._read_json_or_text(resp)
                    if resp.status != 200:
                        err = self._format_error(resp.status, data)
                        last_error = err
                        if not self._should_retry_status(resp.status) or attempt >= max_attempts:
                            return False, err
                        wait_s = delay_base * (2 ** (attempt - 1))
                        logger.warning(
                            f"OpenClaw chat retry {attempt}/{max_attempts - 1}, status={resp.status}, wait={wait_s:.2f}s"
                        )
                        await asyncio.sleep(wait_s)
                        continue
                    choices = data.get("choices") if isinstance(data, dict) else None
                    if isinstance(choices, list) and choices:
                        msg = choices[0].get("message") if isinstance(choices[0], dict) else {}
                        content = ""
                        if isinstance(msg, dict):
                            content = str(msg.get("content") or "").strip()
                        if content:
                            return True, content
                    return False, "OpenClaw 返回为空"
            except Exception as e:
                last_error = str(e) or type(e).__name__
                logger.error(f"OpenClaw chat completions API failed: {last_error}")
                if attempt >= max_attempts:
                    break
                wait_s = delay_base * (2 ** (attempt - 1))
                logger.warning(
                    f"OpenClaw chat retry {attempt}/{max_attempts - 1}, exception={type(e).__name__}, wait={wait_s:.2f}s"
                )
                await asyncio.sleep(wait_s)
        return False, last_error or "OpenClaw 请求失败"

    def _extract_responses_text(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        text = str(data.get("output_text") or "").strip()
        if text:
            return text

        output = data.get("output")
        if not isinstance(output, list):
            return ""

        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for seg in content:
                if not isinstance(seg, dict):
                    continue
                t = str(seg.get("text") or "").strip()
                if t:
                    parts.append(t)
        return "\n".join(parts).strip()

    async def _read_json_or_text(self, resp) -> Any:
        content_type = str(resp.headers.get("Content-Type") or "").lower()
        if "application/json" in content_type:
            try:
                return await resp.json(content_type=None)
            except Exception:
                return {"text": (await resp.text())}
        return {"text": await resp.text()}

    def _format_error(self, status: int, data: Any) -> str:
        if isinstance(data, dict):
            if isinstance(data.get("error"), dict):
                msg = str(data["error"].get("message") or "").strip()
                if msg:
                    return f"HTTP {status}: {msg}"
            if "text" in data:
                return f"HTTP {status}: {str(data.get('text') or '').strip()[:200]}"
        return f"HTTP {status}: {str(data)[:200]}"

    def _should_retry_status(self, status: int) -> bool:
        return status == 429 or status >= 500

    def _auth_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        api_key = str(OPENCLAW_API_KEY or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _build_timeout(self, seconds: float):
        import aiohttp

        return aiohttp.ClientTimeout(total=max(1.0, float(seconds)))
