"""设置/查询应用使用时长限额工具

数字健康功能的一部分: 让用户 (或 Aveline 在对话中) 设置"某应用每天最多用多久",
以及查询当前已设定的限额。限额存于后端 DigitalWellbeingService, 由 ContextSync
随设备上下文下发给 Android 端, Android 本地定时检查超限并强退。

支持相对描述: limit 可为毫秒整数, 或 "1h" / "30m" / "90min" 等人类可读字符串。
target_date 默认明天 (限额总是为"未来的一天"设定)。

注意: 限额改的是后端存储的"计划值", 立即生效并随下次 ContextSync 下发到手机。
"""

import re
from typing import Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("device_tools")


def _parse_duration_to_ms(value) -> Optional[int]:
    """把 limit 参数解析为毫秒。

    接受:
    - 纯整数: 直接当毫秒
    - "1h" / "2小时" / "90min" / "30m" / "45分钟" 等
    - "0" / "none" / "off" / "取消": 表示移除限额, 返回 0
    解析失败返回 None。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().lower()
    if s in ("0", "none", "off", "取消", "无", "remove", "clear"):
        return 0
    # 匹配 "1h" "90min" "30m" "2小时" "45分钟" "1.5h"
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(h|小时|hr|m|分钟|min|s|秒|ms)?$", s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or "ms"
    factor = {
        "h": 3600_000, "小时": 3600_000, "hr": 3600_000,
        "m": 60_000, "分钟": 60_000, "min": 60_000,
        "s": 1000, "秒": 1000,
        "ms": 1,
    }.get(unit, 1)
    return int(num * factor)


def _format_ms(ms: int) -> str:
    """把毫秒格式化成 '1h20m' / '20m' / '30s'。"""
    if ms <= 0:
        return "0m"
    if ms < 60_000:
        return f"{max(ms // 1000, 1)}s"
    total_min = ms // 60_000
    h, m = divmod(total_min, 60)
    return f"{h}h{m}m" if h else f"{m}m"


def _describe_policy(package_name: str, cfg: dict) -> str:
    """把一条限额配置描述成一句话 (每日额度 + 单次额度 + 休息)。"""
    from core.services.digital_wellbeing.service import (
        DEFAULT_COOLDOWN_MS,
        DEFAULT_SESSION_GAP_MS,
    )

    name = cfg.get("app_name") or package_name
    daily_ms = int(cfg.get("limit_ms", 0) or 0)
    session_ms = int(
        cfg.get("session_limit_ms", 0) or cfg.get("session_cap_ms", 0) or 0
    )
    parts = [f"{name} ({package_name})"]
    parts.append(
        f"每日 {_format_ms(daily_ms)}" if daily_ms > 0 else "每日不限"
    )
    if session_ms > 0:
        gap_ms = int(cfg.get("session_gap_ms", 0) or 0) or DEFAULT_SESSION_GAP_MS
        cooldown_ms = int(cfg.get("cooldown_ms", 0) or 0) or DEFAULT_COOLDOWN_MS
        parts.append(f"单次 {_format_ms(session_ms)}")
        parts.append(f"离开 {_format_ms(gap_ms)} 算新的一次")
        parts.append(f"超时休息 {_format_ms(cooldown_ms)}")
    return ", ".join(parts)


class SetAppLimitInput(BaseModel):
    action: str = Field(
        default="set",
        description="操作类型: set=设置/修改限额, get=查询当前限额, list=列出所有限额",
    )
    package_name: Optional[str] = Field(
        default=None,
        description="目标应用包名, 如 com.ss.android.ugc.aweme (抖音)。set/get 时必填",
    )
    app_name: Optional[str] = Field(
        default=None,
        description="应用显示名 (可选, 便于展示, 如 '抖音')",
    )
    limit: Optional[str] = Field(
        default=None,
        description=(
            "每日使用时长上限 (今天总共能用多久)。可填毫秒整数或人类可读字符串: "
            "'1h' / '90min' / '30m' / '2小时'。填 0/无/取消 表示移除每日限额。"
            "与 session_limit 同为 0 时整条移除。"
        ),
    )
    target_date: Optional[str] = Field(
        default=None,
        description="目标日期 YYYY-MM-DD, 默认明天 (限额为未来的某天设定)",
    )
    session_limit: Optional[str] = Field(
        default=None,
        description=(
            "单次连续使用上限 (一次最多连续用多久), 如 '10m' / '5分钟'。"
            "离开超过 2 分钟才算'新的一次', 重新打开又有完整的单次额度; "
            "单次超时后默认休息 5 分钟才能再打开。填 0/无/取消 表示不限单次。"
            "时长同样计入每日总量。"
        ),
    )
    session_gap: Optional[str] = Field(
        default=None,
        description=(
            "离开多久才算'新的一次', 如 '2m' / '5分钟'。小于该间隔的切后台回来"
            "仍算同一次, 防止反复退出重进绕过单次额度。默认 2 分钟。"
        ),
    )
    cooldown: Optional[str] = Field(
        default=None,
        description=(
            "单次超限后多久才能重新打开, 如 '5m' / '10分钟'。默认 5 分钟。"
            "仅在设置了 session_limit 时生效。"
        ),
    )
    session_cap: Optional[str] = Field(
        default=None,
        description=(
            "[兼容旧参数] 等价于 session_limit。新对话请使用 session_limit。"
        ),
    )


class SetAppLimitTool(BaseTool):
    """设置/查询应用使用时长限额 (数字健康)"""

    name = "set_app_limit"
    description = (
        "设置、查询或列出手机应用的使用时长限额 (数字健康功能), 有两类限制且同时生效: "
        "每日限额 (今天总共能用多久) 与单次限额 (一次连续最多用多久)。"
        "例如用户说'抖音每天限1小时', 则 package_name=com.ss.android.ugc.aweme, limit='1h'; "
        "说'每刷10分钟就让我停一下', 则再加 session_limit='10m'。"
        "限额存于后端并下发到手机, 超限时手机会自动退回桌面并通知"
        "(单次超时后默认休息 5 分钟才能再打开)。"
        "action=get 查询单个, action=list 列出全部。仅 Master 可用。"
    )
    short_description = "设置应用使用时长限额 (仅 Master)"
    category = "device"
    enabled_by_default = True
    args_schema = SetAppLimitInput

    def _is_master(self) -> bool:
        cid = str(self._get_ctx("user_id") or "").strip().lower()
        if not cid:
            return False
        if cid in {"default", "default_user"}:
            return True
        session_part = cid.split("__")[0]
        try:
            from clients.bots.qq.settings import MASTER_QQ_ID

            master_id = str(MASTER_QQ_ID or "").strip()
            if master_id and session_part == f"private_{master_id}":
                return True
        except Exception:
            pass
        return False

    def _default_target_date() -> str:
        from core.utils.time_utils import get_current_time

        t = get_current_time()
        import datetime

        # 月末简化: 直接 +1 天 (跨月由 time_utils 的 date 处理, 这里用 timedelta)
        nxt = t.date() + datetime.timedelta(days=1)
        return nxt.strftime("%Y-%m-%d")

    async def _run(
        self,
        action: str = "set",
        package_name: Optional[str] = None,
        app_name: Optional[str] = None,
        limit: Optional[str] = None,
        target_date: Optional[str] = None,
        session_limit: Optional[str] = None,
        session_gap: Optional[str] = None,
        cooldown: Optional[str] = None,
        session_cap: Optional[str] = None,
    ) -> str:
        if not self._is_master():
            return "权限不足: 设备控制工具仅 Master 可用"

        from core.services.digital_wellbeing.service import get_wellbeing_service

        wb = get_wellbeing_service()
        td = target_date or self._default_target_date()
        action = (action or "set").strip().lower()

        # 兼容旧参数名: session_cap == session_limit
        effective_session_limit = session_limit if session_limit is not None else session_cap

        # 只设置单次额度 (每日额度保持不变): 当天生效, 优先于每日额度处理
        if effective_session_limit is not None and limit is None:
            if not package_name:
                return "设置单次限额请提供 package_name"
            session_ms = _parse_duration_to_ms(effective_session_limit)
            if session_ms is None:
                return (
                    "无法解析 session_limit 参数, 请使用毫秒或 '10m' / '5分钟' 格式"
                )
            from core.utils.time_utils import get_current_time as _gct

            today = _gct().strftime("%Y-%m-%d")
            cooldown_ms = _parse_duration_to_ms(cooldown) if cooldown else None
            gap_ms = _parse_duration_to_ms(session_gap) if session_gap else None
            wb.set_single_limit(
                package_name=package_name.strip(),
                limit_ms=0,
                app_name=app_name,
                target_date=today,
                session_limit_ms=session_ms,
                session_gap_ms=gap_ms,
                cooldown_ms=cooldown_ms,
            )
            if session_ms <= 0:
                return f"已清除 {package_name} 的单次限额, 恢复按每日限额判断。"
            return (
                f"已为 {app_name or package_name} ({package_name}) 设定单次限额: "
                f"一次连续使用最多 {_format_ms(session_ms)}"
                f" (该时长计入今日每日总量)。"
                f"离开超过 {_format_ms(gap_ms) if gap_ms else '2m'} 才算新的一次, "
                f"超时后休息 {_format_ms(cooldown_ms) if cooldown_ms else '5m'} 才能再打开。"
            )

        if action == "list":
            data = wb.get_limits(td)
            limits = data.get("limits", {})
            if not limits:
                return f"{td} 暂无应用使用限额设定。"
            lines = [f"{td} 的应用使用限额:"]
            for pkg, cfg in limits.items():
                lines.append(
                    f"- {_describe_policy(pkg, cfg)} [{cfg.get('source', '?')}]"
                )
            return "\n".join(lines)

        if action == "get":
            if not package_name:
                return "查询限额请提供 package_name"
            data = wb.get_limits(td)
            cfg = data.get("limits", {}).get(package_name)
            if not cfg:
                return f"{td} 未对 {package_name} 设定限额。"
            return (
                f"{_describe_policy(package_name, cfg)} "
                f"(来源: {cfg.get('source', '?')})"
            )

        # set
        if not package_name:
            return "设置限额请提供 package_name"
        limit_ms = _parse_duration_to_ms(limit) if limit is not None else 0
        if limit_ms is None:
            return (
                "无法解析 limit 参数, 请使用毫秒整数或如 '1h' / '30m' / '2小时' 的格式"
            )
        session_ms = (
            _parse_duration_to_ms(effective_session_limit)
            if effective_session_limit is not None
            else None
        )
        if session_limit is not None and session_ms is None:
            return "无法解析 session_limit 参数, 请使用毫秒或 '10m' / '5分钟' 格式"
        cooldown_ms = _parse_duration_to_ms(cooldown) if cooldown else None
        gap_ms = _parse_duration_to_ms(session_gap) if session_gap else None
        data = wb.set_single_limit(
            package_name=package_name.strip(),
            limit_ms=limit_ms,
            app_name=app_name,
            target_date=td,
            source="user",
            session_limit_ms=session_ms,
            session_gap_ms=gap_ms,
            cooldown_ms=cooldown_ms,
        )
        cfg = data.get("limits", {}).get(package_name.strip())
        if not cfg:
            return f"已移除 {package_name} 的使用限额。"
        return (
            f"已为 {app_name or package_name} ({package_name}) 设定 {td} 的限额: "
            f"{_describe_policy(package_name, cfg)}。"
            f"该限额将随手机下次同步下发, 超限时手机会自动退回桌面并通知。"
        )
