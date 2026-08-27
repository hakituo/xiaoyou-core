from __future__ import annotations

from typing import Any


async def handle_study_mode(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    prefs = ctx["prefs"]
    cmd_lower = str(ctx.get("cmd_lower") or "").strip().lower()
    arg = str(ctx["rest"] or "").strip().lower()

    current_mode = str(prefs.get("mode") or "normal").strip().lower() or "normal"
    if not arg or arg in {"status", "状态"}:
        if cmd_lower in {"学习模式", "study_mode", "studymode"}:
            state = "开启" if current_mode == "study" else "关闭"
            await router.adapter.send_to_napcat(
                sid,
                f"当前学习模式：{state}。使用 /学习模式 on/off 切换",
            )
        else:
            await router.adapter.send_to_napcat(
                sid,
                f"当前模式：{current_mode}。用法：/模式 <study|normal|privacy|entertainment>",
            )
        return True

    mode_map = {
        "study": "study",
        "learning": "study",
        "学习": "study",
        "on": "study",
        "开启": "study",
        "开": "study",
        "normal": "normal",
        "普通": "normal",
        "off": "normal",
        "关闭": "normal",
        "关": "normal",
        "privacy": "privacy",
        "隐私": "privacy",
        "私密": "privacy",
        "entertainment": "entertainment",
        "娱乐": "entertainment",
    }

    mode = mode_map.get(arg)
    if cmd_lower in {"学习模式", "study_mode", "studymode"}:
        if arg in {"privacy", "隐私", "私密"}:
            mode = "privacy"
        elif arg in {"entertainment", "娱乐"}:
            mode = "entertainment"
    if not mode:
        await router.adapter.send_to_napcat(sid, f"未知模式：{arg}")
        return True

    await router.adapter.config_handler.update_session_config(sid, "mode", mode)
    await router.adapter.send_to_napcat(sid, f"已切换到模式：{mode}")
    return True


async def handle_privacy_mode(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    prefs = ctx["prefs"]
    arg = str(ctx["rest"] or "").strip().lower()
    current_mode = str(prefs.get("mode") or "normal").strip().lower() or "normal"
    if not arg or arg in {"status", "状态"}:
        state = "开启" if current_mode == "privacy" else "关闭"
        await router.adapter.send_to_napcat(
            sid,
            f"当前私密模式：{state}。使用 /私密模式 on/off 切换",
        )
        return True
    if arg in {"on", "true", "1", "开启", "开"}:
        mode = "privacy"
    elif arg in {"off", "false", "0", "关闭", "关"}:
        mode = "normal"
    else:
        await router.adapter.send_to_napcat(sid, "用法：/私密模式 <on/off/status>")
        return True
    await router.adapter.config_handler.update_session_config(sid, "mode", mode)
    await router.adapter.send_to_napcat(sid, f"已切换到模式：{mode}")
    return True


async def handle_latency(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    prefs = ctx["prefs"]
    arg = str(ctx["rest"] or "").strip().lower()

    if not arg:
        state = "开启" if bool(prefs.get("bionic_delay", True)) else "关闭"
        await router.adapter.send_to_napcat(
            sid,
            f"当前仿生延迟状态：{state} (默认开启)",
        )
        return True

    new_state = arg in {"on", "true", "1", "开启", "开"}
    prefs["bionic_delay"] = new_state
    await router.adapter.config_handler.update_session_config(
        sid,
        "bionic_delay",
        new_state,
    )
    state = "开启" if new_state else "关闭"
    await router.adapter.send_to_napcat(sid, f"已{state}仿生延迟。")
    return True


async def handle_reply_mode(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    arg = str(ctx["rest"] or "").strip().lower()
    if arg not in {"at", "all"}:
        current = router.adapter.reply_mode
        await router.adapter.send_to_napcat(
            sid,
            f"当前回复模式：{current}。用法：/回复模式 <at/all>",
        )
        return True

    router.adapter.reply_mode = "at_only" if arg == "at" else "all"
    await router.adapter.send_to_napcat(
        sid,
        f"已切换回复模式为：{router.adapter.reply_mode}",
    )
    return True


async def handle_voice_only(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    prefs = ctx["prefs"]
    qq_user_id = ctx.get("qq_user_id")
    arg = str(ctx["rest"] or "").strip().lower()

    if arg in {"on", "true", "1", "开启"}:
        prefs["reply_voice_only"] = True
        await router.adapter.config_handler.update_global_config("reply_voice_only", True)
        try:
            await router.adapter.config_handler.persist_user_override(
                str(qq_user_id or ""),
                prefs,
            )
        except Exception:
            pass
        await router.adapter.send_to_napcat(
            sid,
            "已开启：仅语音回复（文字将被抑制）。",
        )
        return True

    if arg in {"off", "false", "0", "关闭"}:
        prefs["reply_voice_only"] = False
        await router.adapter.config_handler.update_global_config("reply_voice_only", False)
        try:
            await router.adapter.config_handler.persist_user_override(
                str(qq_user_id or ""),
                prefs,
            )
        except Exception:
            pass
        await router.adapter.send_to_napcat(
            sid,
            "已关闭：仅语音回复（恢复文字回复）。",
        )
        return True

    current = "开启" if bool(prefs.get("reply_voice_only")) else "关闭"
    await router.adapter.send_to_napcat(
        sid,
        f"当前仅语音回复状态：{current}。使用 /只语音 on/off 切换",
    )
    return True


async def handle_openclaw(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    prefs = ctx["prefs"]
    arg = str(ctx["rest"] or "").strip()
    if not arg:
        await router.adapter.openclaw_handler.show_help(sid)
        return True

    parts = arg.split(None, 1)
    sub = parts[0].lower()
    sub_rest = parts[1] if len(parts) > 1 else ""

    if sub in {"状态", "status"}:
        await router.adapter.openclaw_handler.show_status(sid, prefs)
        return True
    if sub in {"模型", "model"}:
        await router.adapter.openclaw_handler.set_or_show_model(sid, prefs, sub_rest)
        return True
    if sub in {"模型列表", "models"}:
        await router.adapter.openclaw_handler.show_models(sid)
        return True

    await router.adapter.openclaw_handler.handle_task(sid, arg, prefs)
    return True


async def handle_web_search(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    prefs = ctx["prefs"]
    query = str(ctx["rest"] or "").strip()
    if not query:
        await router.adapter.send_to_napcat(sid, "用法：/搜索 <关键词>")
        return True
    await router.adapter.openclaw_handler.handle_web_search(sid, query, prefs)
    return True


async def handle_sid(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    qq = ctx["qq_user_id"]
    grp = ctx["group_id"]
    msg_type = ctx["msg_type"]
    info = f"Session ID: {sid}\nQQ User: {qq}\nGroup: {grp}\nType: {msg_type}"
    await router.adapter.send_to_napcat(sid, info)
    return True


async def handle_meme(router: Any, **ctx) -> bool:
    sid = ctx["session_id"]
    arg = str(ctx["rest"] or "").strip()
    if arg in {"列表", "list"}:
        await router.adapter.meme_handler.show_categories(sid)
        return True
    await router.adapter.meme_handler.send_meme(sid, arg)
    return True
