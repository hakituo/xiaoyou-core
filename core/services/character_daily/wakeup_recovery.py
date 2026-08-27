"""角色起床后的积压事项恢复。"""

from __future__ import annotations

from typing import Any, Dict

from core.services.character_daily.night_patch import build_night_patch_decision


def _build_sleep_impact_line(sleep_summary: Dict[str, Any]) -> str:
    """把睡眠影响等级解释成人能看懂的原因说明。"""
    impact_level = str(sleep_summary.get("impact_level") or "").strip()
    if impact_level in {"", "none"}:
        return ""

    nightmare_level = str(sleep_summary.get("nightmare_level") or "none").strip()
    sleep_debt_hours = float(sleep_summary.get("sleep_debt_hours") or 0.0)

    if nightmare_level != "none" and sleep_debt_hours >= 0.3:
        return (
            f"睡眠影响等级：{impact_level}（主要受噩梦影响，且有约 {sleep_debt_hours:.1f} 小时睡眠债）。"
        )
    if nightmare_level != "none":
        return f"睡眠影响等级：{impact_level}（主要受昨夜噩梦影响）。"
    if sleep_debt_hours >= 0.3:
        return f"睡眠影响等级：{impact_level}（主要受约 {sleep_debt_hours:.1f} 小时睡眠债影响）。"
    return f"睡眠影响等级：{impact_level}。"


def build_wakeup_recovery_summary(
    *,
    role_name: str,
    sleep_summary: Dict[str, Any],
    schedule_adjust_tendency: float,
    diary_backfill_tendency: float,
) -> str:
    """构建起床后的恢复摘要。"""
    patch = build_night_patch_decision(
        schedule_adjust_tendency=schedule_adjust_tendency,
        diary_backfill_tendency=diary_backfill_tendency,
        patch_pending=bool(sleep_summary.get("patch_pending")),
    )
    lines = [f"{role_name}刚起床。"]
    if sleep_summary.get("overslept"):
        lines.append("她今天有点睡过头。")
    impact_line = _build_sleep_impact_line(sleep_summary)
    if impact_line:
        lines.append(impact_line)
    if patch.should_adjust_plan:
        lines.append("她有一定概率会轻微调整今天的安排。")
    elif patch.should_backfill_diary:
        lines.append("她低概率会回头补一点昨晚漏掉的记录。")
    elif patch.should_ignore:
        lines.append("大概率不会特地补救，先按当前状态往下过。")
    return "\n".join(lines)
