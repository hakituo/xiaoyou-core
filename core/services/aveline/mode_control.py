from typing import Any, Dict, Optional, Tuple


async def handle_natural_mode_control(
    user_input_lower: str, prefs: Any
) -> Optional[Tuple[str, Dict[str, Any]]]:
    target_mode = None

    if any(
        x in user_input_lower
        for x in [
            "切换到隐私模式",
            "开启隐私模式",
            "打开隐私模式",
            "enter privacy mode",
        ]
    ):
        target_mode = "privacy"
    elif any(
        x in user_input_lower
        for x in [
            "切换到正常模式",
            "回到正常模式",
            "退出隐私模式",
            "enter normal mode",
        ]
    ):
        target_mode = "normal"
    elif any(
        x in user_input_lower
        for x in [
            "切换到学习模式",
            "开启学习模式",
            "我要学习了",
            "enter study mode",
        ]
    ):
        target_mode = "study"
    elif any(
        x in user_input_lower for x in ["退出学习模式", "结束学习", "exit study mode"]
    ):
        target_mode = "normal"

    if not target_mode:
        return None

    old_mode = str(prefs.get_mode() or "normal")
    await prefs.set_mode(target_mode)
    try:
        from core.services.active_care.core.service import get_active_care_service

        await get_active_care_service().on_mode_switch(target_mode, old_mode)
    except Exception:
        pass

    if target_mode == "privacy":
        return "已切换到【隐私模式】。所有数据将仅保存在本地。", {
            "status": "success",
            "command": "mode",
            "mode": "privacy",
        }
    if target_mode == "study":
        return "已切换到【学习模式】。让我们开始专注学习吧。", {
            "status": "success",
            "command": "mode",
            "mode": "study",
        }
    return "已切换回【正常模式】。", {
        "status": "success",
        "command": "mode",
        "mode": "normal",
    }

