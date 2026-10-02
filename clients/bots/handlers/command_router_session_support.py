from __future__ import annotations

from typing import Any

from clients.bots.qq.utils import _truncate_text, build_persona_conversation_id


async def handle_history(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    rest = str(ctx["rest"] or "").strip()
    target_sid = sid
    limit = 10

    parts = rest.split()
    if len(parts) == 1:
        if parts[0].isdigit():
            limit = int(parts[0])
        else:
            target_sid = parts[0]
    elif len(parts) >= 2:
        target_sid = parts[0]
        if parts[1].isdigit():
            limit = int(parts[1])

    limit = min(50, max(1, limit))
    status, data = await router.adapter._api_request(
        "GET",
        f"/api/v1/sessions/{target_sid}/history",
        params={"limit": limit},
    )

    if status != 200:
        await router.adapter.send_to_napcat(sid, f"获取历史失败 ({status})")
        return True

    msgs = data.get("data", []) if isinstance(data.get("data"), list) else []
    if not msgs:
        await router.adapter.send_to_napcat(sid, "无历史记录")
        return True

    lines = [f"会话 {target_sid} 最近 {len(msgs)} 条消息："]
    for item in msgs:
        role = item.get("role", "unknown")
        content = _truncate_text(str(item.get("content", "")), 50)
        lines.append(f"[{role}] {content}")

    await router.adapter.send_to_napcat(sid, "\n".join(lines))
    return True


async def handle_session_list(router: Any, **ctx) -> bool:
    status, data = await router.adapter._api_request(
        "GET",
        "/api/v1/sessions?include_external=true",
    )
    if status != 200:
        await router.adapter.send_to_napcat(ctx["session_id"], "获取会话列表失败")
        return True

    sessions = data.get("data", [])
    if not sessions:
        await router.adapter.send_to_napcat(ctx["session_id"], "无活跃会话")
        return True

    lines = ["活跃会话列表："]
    for item in sessions[:20]:
        sid = item.get("id")
        title = item.get("title", "未命名")
        lines.append(f"- {sid} ({title})")

    await router.adapter.send_to_napcat(ctx["session_id"], "\n".join(lines))
    return True


async def handle_session_rename(router: Any, **ctx) -> bool:
    parts = str(ctx["rest"] or "").split(None, 1)
    if len(parts) < 2:
        await router.adapter.send_to_napcat(
            ctx["session_id"],
            "用法：/会话重命名 <session_id> <新标题>",
        )
        return True

    target_sid, new_title = parts
    status, _ = await router.adapter._api_request(
        "PUT",
        f"/api/v1/sessions/{target_sid}",
        json_body={"title": new_title},
    )

    if status == 200:
        await router.adapter.send_to_napcat(
            ctx["session_id"],
            f"会话 {target_sid} 已重命名为 {new_title}",
        )
    else:
        await router.adapter.send_to_napcat(ctx["session_id"], "重命名失败")
    return True


async def handle_session_delete(router: Any, **ctx) -> bool:
    target_sid = str(ctx["rest"] or "").strip()
    if not target_sid:
        await router.adapter.send_to_napcat(
            ctx["session_id"],
            "用法：/删除会话 <session_id>",
        )
        return True

    status, _ = await router.adapter._api_request(
        "DELETE",
        f"/api/v1/sessions/{target_sid}",
    )
    if status == 200:
        await router.adapter.send_to_napcat(
            ctx["session_id"],
            f"会话 {target_sid} 已删除",
        )
    else:
        await router.adapter.send_to_napcat(ctx["session_id"], "删除失败")
    return True


def _resolve_memory_target_ids(router: Any, session_id: str, prefs: dict | None) -> list[str]:
    base_id = str(session_id or "").strip() or "default_user"
    persona_filename = str((prefs or {}).get("persona_filename") or "").strip()
    persona_id = build_persona_conversation_id(base_id, persona_filename)

    try:
        from core.utils.data_paths import resolve_memory_user_id

        scope_id = resolve_memory_user_id(persona_id)
    except Exception:
        scope_id = None

    result: list[str] = []
    if scope_id and scope_id not in result:
        result.append(scope_id)
    if persona_id not in result:
        result.append(persona_id)
    if base_id not in result:
        result.append(base_id)
    return result


async def handle_clear_short_memory(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    target_ids = _resolve_memory_target_ids(router, sid, ctx.get("prefs"))

    logger = router.adapter.logger if hasattr(router.adapter, "logger") else None
    if logger:
        logger.info(f"[清除短期记忆] session_id={sid}, target_ids={target_ids}")

    statuses = []
    for target_id in target_ids:
        status, data = await router.adapter._api_request(
            "POST",
            "/api/v1/memories/clear",
            json_body={"user_id": target_id, "mode": "short"},
        )
        statuses.append(status)
        if logger:
            logger.info(
                f"[清除短期记忆] target_id={target_id}, status={status}, response={data}",
            )

    if any(item == 200 for item in statuses):
        await router.adapter.send_to_napcat(
            sid,
            "短期记忆已清除（对话上下文重置）。",
        )
    else:
        await router.adapter.send_to_napcat(sid, f"清除失败，状态码: {statuses}")
    return True


async def handle_clear_all_memory(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    if "confirm" not in str(ctx["rest"] or ""):
        await router.adapter.send_to_napcat(
            sid,
            "警告：这将彻底删除本地所有历史记忆！确认请发送：/清除本地记忆 confirm",
        )
        return True

    target_ids = _resolve_memory_target_ids(router, sid, ctx.get("prefs"))
    statuses = []
    for target_id in target_ids:
        status, _ = await router.adapter._api_request(
            "POST",
            "/api/v1/memories/clear",
            json_body={"user_id": target_id, "mode": "all"},
        )
        statuses.append(status)
    if any(item == 200 for item in statuses):
        await router.adapter.send_to_napcat(sid, "本地记忆已全部清除。")
    else:
        await router.adapter.send_to_napcat(sid, "清除失败")
    return True


async def handle_debug_mode(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    prefs = ctx["prefs"]

    current = bool(prefs.get("debug_mode", False))
    new_state = not current
    prefs["debug_mode"] = new_state
    await router.adapter.config_handler.update_session_config(
        sid,
        "debug_mode",
        new_state,
    )

    state = "开启" if new_state else "关闭"
    await router.adapter.send_to_napcat(
        sid,
        f"调试模式已{state}（不保存历史）。",
    )
    return True


async def handle_regenerate(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    prefs = ctx.get("prefs") or {}

    persona_filename = str(prefs.get("persona_filename") or "").strip()
    conversation_id = (
        build_persona_conversation_id(sid, persona_filename)
        if persona_filename
        else sid
    )

    status, data = await router.adapter._api_request(
        "POST",
        "/api/v1/regenerate",
        json_body={"conversation_id": conversation_id},
        timeout_seconds=120.0,
    )

    if status != 200:
        error_message = "重新生成失败"
        if isinstance(data, dict):
            error_message = data.get("message") or data.get("error") or error_message
        await router.adapter.send_to_napcat(sid, error_message)
        return True

    response_text = ""
    if isinstance(data, dict):
        response_text = data.get("response") or data.get("reply") or ""

    if not response_text:
        await router.adapter.send_to_napcat(
            sid,
            "重新生成完成，但没有收到回复。",
        )
        return True

    await router.adapter.send_to_napcat(sid, f"🔄 重新生成：\n{response_text}")
    return True


async def handle_split_toggle(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    arg = str(ctx.get("rest") or "").strip().lower()

    session = router.adapter.sessions.get(sid)
    if not session:
        await router.adapter.send_to_napcat(sid, "会话不存在")
        return True

    if not arg or arg in {"status", "状态"}:
        state = "关闭（整段发送）" if session._split_disabled else "开启"
        await router.adapter.send_to_napcat(
            sid,
            f"当前断句：{state}。使用 /断句 on/off 切换",
        )
        return True

    if arg in {"on", "开", "开启", "true", "yes"}:
        session._split_disabled = False
        await router.adapter.send_to_napcat(sid, "断句已开启")
        return True
    if arg in {"off", "关", "关闭", "false", "no"}:
        session._split_disabled = True
        await router.adapter.send_to_napcat(
            sid,
            "断句已关闭（回复将整段发送）",
        )
        return True

    await router.adapter.send_to_napcat(sid, f"未知参数：{arg}。用法：/断句 on/off")
    return True


async def handle_tts_mode(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    arg = str(ctx.get("rest") or "").strip().lower()

    if not arg or arg in {"status", "状态"}:
        try:
            from core.voice.tts_engine import get_tts_manager

            tts = get_tts_manager()
            tts_config = tts.settings.voice.tts
            current = str(tts_config.provider or "").strip().lower()
            if current in {"volcano", "volcengine", "字节", "火山", "cloud"}:
                state = "云端（火山引擎）"
            elif current in {"qwen3", "local", "本地"}:
                state = "本地（Qwen3）"
            else:
                state = current or "未知"
            await router.adapter.send_to_napcat(
                sid,
                f"当前TTS模式：{state}\n用法：/tts模式 cloud（云端）或 /tts模式 local（本地）",
            )
        except Exception as exc:
            await router.adapter.send_to_napcat(sid, f"获取TTS状态失败: {exc}")
        return True

    try:
        from core.voice.tts_engine import get_tts_manager

        tts = get_tts_manager()
        result = await tts.switch_engine(arg)
        await router.adapter.send_to_napcat(sid, result)
    except Exception as exc:
        await router.adapter.send_to_napcat(sid, f"切换TTS模式失败: {exc}")
    return True


def _resolve_wake_payload(router: Any, session_id: str, prefs: dict | None, rest: str) -> dict[str, str]:
    persona_filename = str((prefs or {}).get("persona_filename") or "").strip()
    adapter_cfg = getattr(router.adapter, "cfg", None)
    role_id = str(getattr(adapter_cfg, "role_id", "") or "").strip().lower()
    conversation_id = (
        build_persona_conversation_id(session_id, persona_filename)
        if persona_filename
        else str(session_id or "").strip()
    )
    message = str(rest or "").strip() or "QQ命令立即唤醒"
    return {
        "role_id": role_id,
        "persona_filename": persona_filename,
        "conversation_id": conversation_id,
        "message": message,
    }


async def handle_sleep_wake(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    payload = _resolve_wake_payload(
        router,
        ctx["session_id"],
        ctx.get("prefs"),
        str(ctx.get("rest") or ""),
    )
    status, data = await router.adapter._api_request(
        "POST",
        "/api/v1/life/sleep/wake",
        json_body=payload,
    )
    if status != 200 or not isinstance(data, dict):
        await router.adapter.send_to_napcat(sid, f"唤醒失败 ({status})")
        return True

    action = str(data.get("action") or "").strip()
    resolved_role = str(data.get("role_id") or "").strip() or "当前角色"
    summary = data.get("sleep_summary") if isinstance(data.get("sleep_summary"), dict) else {}
    phase = str(summary.get("phase") or "unknown")

    if action == "woken_up":
        await router.adapter.send_to_napcat(
            sid,
            f"已立即唤醒 `{resolved_role}`，当前状态：{phase}",
        )
        return True

    if action == "already_awake":
        await router.adapter.send_to_napcat(
            sid,
            f"`{resolved_role}` 当前没在睡，状态：{phase}",
        )
        return True

    error_message = str(data.get("message") or data.get("error") or "唤醒失败").strip()
    await router.adapter.send_to_napcat(sid, error_message)
    return True


async def handle_activity_interrupt(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    payload = _resolve_wake_payload(
        router,
        ctx["session_id"],
        ctx.get("prefs"),
        str(ctx.get("rest") or ""),
    )
    status, data = await router.adapter._api_request(
        "POST",
        "/api/v1/life/activity/interrupt",
        json_body=payload,
    )
    if status != 200 or not isinstance(data, dict):
        await router.adapter.send_to_napcat(sid, f"打断失败 ({status})")
        return True

    action = str(data.get("action") or "").strip()
    resolved_role = str(data.get("role_id") or "").strip() or "当前角色"
    activity = str(data.get("activity") or "unknown").strip()
    window_seconds = int(data.get("window_seconds") or 0)

    if action == "interrupted":
        await router.adapter.send_to_napcat(
            sid,
            f"已打断 `{resolved_role}` 的 `{activity}`，接下来约 {window_seconds} 秒内会优先继续和你聊天。",
        )
        return True

    if action == "already_available":
        await router.adapter.send_to_napcat(
            sid,
            f"`{resolved_role}` 现在本来就在空闲状态，不用额外打断。",
        )
        return True

    if action == "already_skipped":
        # 当前活动已被 /跳过活动 标记为 skip，/打断 不应覆盖 /skip 的长窗口
        remaining_display = str(data.get("remaining_display") or "").strip()
        suffix = f"（约 {remaining_display}）" if remaining_display else ""
        await router.adapter.send_to_napcat(
            sid,
            f"`{resolved_role}` 当前活动已经被跳过{suffix}，"
            "这段时间都能继续聊天，不需要再打断。",
        )
        return True

    if action == "sleeping_use_wake":
        await router.adapter.send_to_napcat(
            sid,
            f"`{resolved_role}` 当前属于睡眠相关状态，请先用 `/唤醒`。",
        )
        return True

    error_message = str(data.get("message") or data.get("error") or "打断失败").strip()
    await router.adapter.send_to_napcat(sid, error_message)
    return True


async def handle_activity_skip(router: Any, **ctx) -> bool:
    """处理 /跳过活动 命令：标记跳过当前活动，不再提醒回去做事。"""
    sid = ctx["session_id"]
    payload = _resolve_wake_payload(
        router,
        ctx["session_id"],
        ctx.get("prefs"),
        str(ctx.get("rest") or ""),
    )
    status, data = await router.adapter._api_request(
        "POST",
        "/api/v1/life/activity/skip",
        json_body=payload,
    )
    if status != 200 or not isinstance(data, dict):
        await router.adapter.send_to_napcat(sid, f"跳过活动失败 ({status})")
        return True

    action = str(data.get("action") or "").strip()
    resolved_role = str(data.get("role_id") or "").strip() or "当前角色"
    activity = str(data.get("activity") or "unknown").strip()
    remaining_display = str(data.get("remaining_display") or "").strip()

    if action == "skipped":
        await router.adapter.send_to_napcat(
            sid,
            f"已跳过 `{resolved_role}` 的 `{activity}`，"
            f"接下来约 {remaining_display} 内继续聊天，不会再提醒回去做事了。",
        )
        return True

    if action == "auto_skipped":
        await router.adapter.send_to_napcat(
            sid,
            f"已自动打断并跳过 `{resolved_role}` 的 `{activity}`，"
            f"接下来约 {remaining_display} 内继续聊天，不会再提醒回去做事了。",
        )
        return True

    if action == "no_interrupt_window":
        await router.adapter.send_to_napcat(
            sid,
            f"`{resolved_role}` 当前没有活跃的中断窗口，"
            "请先使用 `/打断` 打断忙碌状态。",
        )
        return True

    if action == "already_available":
        await router.adapter.send_to_napcat(
            sid,
            f"`{resolved_role}` 现在本来就在空闲状态，不需要跳过活动。",
        )
        return True

    if action == "sleeping_use_wake":
        await router.adapter.send_to_napcat(
            sid,
            f"`{resolved_role}` 当前属于睡眠相关状态，请先用 `/唤醒`。",
        )
        return True

    error_message = str(data.get("message") or data.get("error") or "跳过失败").strip()
    await router.adapter.send_to_napcat(sid, error_message)
    return True


async def handle_activity_extend(router: Any, **ctx) -> bool:
    """处理 /继续聊 命令：延长中断窗口时间。"""
    sid = ctx["session_id"]
    rest = str(ctx.get("rest") or "")

    # 解析延长秒数（可选参数）
    extend_seconds = 300
    rest_stripped = rest.strip()
    if rest_stripped and rest_stripped.isdigit():
        extend_seconds = max(60, min(600, int(rest_stripped)))

    payload = _resolve_wake_payload(
        router,
        ctx["session_id"],
        ctx.get("prefs"),
        str(ctx.get("rest") or ""),
    )
    payload["extend_seconds"] = extend_seconds
    status, data = await router.adapter._api_request(
        "POST",
        "/api/v1/life/activity/extend",
        json_body=payload,
    )
    if status != 200 or not isinstance(data, dict):
        await router.adapter.send_to_napcat(sid, f"延长窗口失败 ({status})")
        return True

    action = str(data.get("action") or "").strip()
    resolved_role = str(data.get("role_id") or "").strip() or "当前角色"
    # activity 在回复消息中不需要，但保留用于日志
    _activity = str(data.get("activity") or "unknown").strip()
    extended_count = int(data.get("extended_count") or 0)
    remaining = int(data.get("remaining_seconds") or 0)

    if action == "extended":
        await router.adapter.send_to_napcat(
            sid,
            f"已延长 `{resolved_role}` 的聊天窗口 {extend_seconds} 秒，"
            f"当前剩余约 {remaining} 秒（已延长 {extended_count} 次）。",
        )
        return True

    if action == "no_window_or_max_extended":
        await router.adapter.send_to_napcat(
            sid,
            f"`{resolved_role}` 当前没有活跃的中断窗口，"
            "或已达到延长上限（最多 3 次）。请先使用 `/打断`。",
        )
        return True

    error_message = str(data.get("message") or data.get("error") or "延长失败").strip()
    await router.adapter.send_to_napcat(sid, error_message)
    return True
