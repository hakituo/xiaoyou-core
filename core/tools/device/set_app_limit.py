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
            "每日使用时长上限。可填毫秒整数或人类可读字符串: "
            "'1h' / '90min' / '30m' / '2小时'。填 0/无/取消 表示移除限额。set 时必填"
        ),
    )
    target_date: Optional[str] = Field(
        default=None,
        description="目标日期 YYYY-MM-DD, 默认明天 (限额为未来的某天设定)",
    )
    session_cap: Optional[str] = Field(
        default=None,
        description=(
            "会话限额(一次性 cap), 如 '10m' / '5分钟'。设置后该应用「本次」只能用这么久, "
            "时长计入当日每日总量; 填 0/无/取消 清除会话 cap, 回到仅按每日限额判断。"
            "不填则只操作每日限额。会话 cap 当天生效, 跨天自动失效。"
        ),
    )


class SetAppLimitTool(BaseTool):
    """设置/查询应用使用时长限额 (数字健康)"""

    name = "set_app_limit"
    description = (
        "设置、查询或列出手机应用的使用时长每日限额 (数字健康功能)。"
        "例如用户说'抖音每天限1小时', 则 package_name=com.ss.android.ugc.aweme, "
        "limit='1h'。限额存于后端并下发到手机, 手机会在超限时自动强制退出该应用并通知。"
        "支持 session_cap 参数设置'会话限额'(一次性 cap): 用户说'我休息好了去玩10分钟'时, "
        "传 session_cap='10m', 该应用本次只能用 10 分钟, 时长计入每日总量, 说'恢复'可解除。"
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
        session_cap: Optional[str] = None,
    ) -> str:
        if not self._is_master():
            return "权限不足: 设备控制工具仅 Master 可用"

        from core.services.digital_wellbeing.service import get_wellbeing_service

        wb = get_wellbeing_service()
        td = target_date or self._default_target_date()
        action = (action or "set").strip().lower()

        # 会话限额 (一次性 cap): 当天生效, 优先于每日限额处理
        if session_cap is not None:
            if not package_name:
                return "设置会话限额请提供 package_name"
            cap_ms = _parse_duration_to_ms(session_cap)
            if cap_ms is None:
                return (
                    "无法解析 session_cap 参数, 请使用毫秒或 '10m' / '5分钟' 格式"
                )
            from core.utils.time_utils import get_current_time as _gct

            today = _gct().strftime("%Y-%m-%d")
            wb.set_session_cap(
                package_name=package_name.strip(),
                session_cap_ms=cap_ms,
                app_name=app_name,
                target_date=today,
            )
            if cap_ms <= 0:
                return f"已清除 {package_name} 的会话限额, 恢复按每日限额判断。"
            h = cap_ms // 3600_000
            m = (cap_ms % 3600_000) // 60_000
            dur = f"{h}h{m}m" if h else f"{m}m"
            return (
                f"已为 {app_name or package_name} ({package_name}) 设定会话限额: "
                f"本次累计使用 {dur} (该时长计入今日每日总量)。"
                f"超限时手机会自动强退该应用, 说\"恢复\"可解除。"
            )

        if action == "list":
            data = wb.get_limits(td)
            limits = data.get("limits", {})
            if not limits:
                return f"{td} 暂无应用使用限额设定。"
            lines = [f"{td} 的应用使用限额:"]
            for pkg, cfg in limits.items():
                ms = cfg.get("limit_ms", 0)
                h = ms // 3600_000
                m = (ms % 3600_000) // 60_000
                dur = f"{h}h{m}m" if h else f"{m}m"
                lines.append(
                    f"- {cfg.get('app_name', pkg)} ({pkg}): {dur} "
                    f"[{cfg.get('source', '?')}]"
                )
            return "\n".join(lines)

        if action == "get":
            if not package_name:
                return "查询限额请提供 package_name"
            data = wb.get_limits(td)
            cfg = data.get("limits", {}).get(package_name)
            if not cfg:
                return f"{td} 未对 {package_name} 设定限额。"
            ms = cfg.get("limit_ms", 0)
            h = ms // 3600_000
            m = (ms % 3600_000) // 60_000
            dur = f"{h}h{m}m" if h else f"{m}m"
            return f"{cfg.get('app_name', package_name)} ({package_name}) 的限额为 {dur} (来源: {cfg.get('source', '?')})"

        # set
        if not package_name:
            return "设置限额请提供 package_name"
        limit_ms = _parse_duration_to_ms(limit)
        if limit_ms is None:
            return (
                "无法解析 limit 参数, 请使用毫秒整数或如 '1h' / '30m' / '2小时' 的格式"
            )
        data = wb.set_single_limit(
            package_name=package_name.strip(),
            limit_ms=limit_ms,
            app_name=app_name,
            target_date=td,
            source="user",
        )
        if limit_ms <= 0:
            return f"已移除 {package_name} 的使用限额。"
        h = limit_ms // 3600_000
        m = (limit_ms % 3600_000) // 60_000
        dur = f"{h}h{m}m" if h else f"{m}m"
        return (
            f"已为 {app_name or package_name} ({package_name}) 设定 {td} 的使用限额: {dur}。"
            f"该限额将随手机下次同步下发, 当日用量超限时手机会自动强制退出该应用。"
        )
