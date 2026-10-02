"""主动关怀跨角色提醒上下文。"""

from __future__ import annotations

import json


def _build_other_persona_reminders_text(persona_filename: str) -> str:
    """构建其他角色今日已认领的提醒，避免重复发送。"""
    from core.services.dual_role.personas import find_persona_by_filename_hint, get_persona
    from core.utils.data_paths import get_dual_role_reminder_assignment_path
    from core.utils.time_utils import get_current_time

    try:
        path = get_dual_role_reminder_assignment_path()
        if not path.exists():
            return ""
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return ""
        if str(data.get("date", "")) != get_current_time().strftime("%Y-%m-%d"):
            return ""
        assignments = data.get("assignments") or []
        if not assignments:
            return ""
        profile = find_persona_by_filename_hint(persona_filename)
        if profile is None:
            return ""

        other_items = []
        other_names = []
        for assignment in assignments:
            if not isinstance(assignment, dict):
                continue
            assigned = str(assignment.get("assigned_to", "")).strip().lower()
            if not assigned or assigned == profile.role_id:
                continue
            title = str(assignment.get("title") or "").strip()
            if not title:
                continue
            other_items.append(title)
            peer = get_persona(assigned)
            name = (peer.cn_name if peer else "") or (peer.en_name if peer else "") or assigned
            if name not in other_names:
                other_names.append(name)
        if not other_items:
            return ""
        items_text = "\n".join(f"- {title}" for title in other_items[:5])
        other_name_text = "、".join(other_names) if other_names else "另一角色"
        return (
            "\n\n========== 另一角色今日已发提醒 ==========\n"
            f"{other_name_text}今天已经发过以下提醒，请避免重复相同内容：\n"
            f"{items_text}\n"
            "你可以从不同角度补充，或选择其他话题。\n"
            "=================================================\n"
        )
    except Exception:  # noqa: BLE001
        return ""
