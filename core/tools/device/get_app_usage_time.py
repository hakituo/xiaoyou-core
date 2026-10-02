"""查询应用使用时长工具 (UsageStatsManager)"""

from typing import Optional

from pydantic import BaseModel, Field

from .base import DeviceToolBase


class GetAppUsageTimeInput(BaseModel):
    package_name: Optional[str] = Field(
        default=None,
        description="可选, 指定单一包名查询; 不填则返回 Top N 应用",
    )
    since_hours: int = Field(
        default=24,
        description="回溯小时数, 默认 24 (查过去 24 小时)",
    )
    limit: int = Field(
        default=10,
        description="返回 Top N 条, 默认 10",
    )
    include_system_apps: bool = Field(
        default=False,
        description="是否包含系统应用, 默认 false",
    )


class GetAppUsageTimeTool(DeviceToolBase):
    """查询手机应用使用时长 (UsageStatsManager)"""

    name = "get_app_usage_time"
    description = (
        "查询手机应用使用时长 (前台停留时间)。可按包名单查, 也可返回 Top N。"
        "需用户已授予使用情况访问权限 (Usage Access)。"
        "用于主动关怀和学习监督 (如查询用户今天刷了多久抖音)。仅 Master 可用。"
    )
    short_description = "查询手机应用使用时长 (仅 Master)"
    args_schema = GetAppUsageTimeInput

    async def _run(
        self,
        package_name: Optional[str] = None,
        since_hours: int = 24,
        limit: int = 10,
        include_system_apps: bool = False,
    ) -> str:
        safe_hours = max(1, min(int(since_hours or 24), 24 * 30))  # 最多 30 天
        safe_limit = max(1, min(int(limit or 10), 50))
        args = {
            "since_hours": safe_hours,
            "limit": safe_limit,
            "include_system_apps": bool(include_system_apps),
        }
        if package_name and package_name.strip():
            args["package_name"] = package_name.strip()
        return await self._execute("get_app_usage_time", args, timeout=15.0)

    def _format_success(self, data):
        entries = data.get("entries", [])
        if not entries:
            return "没有使用时长数据 (可能未授权 Usage Access 或时间范围内无使用记录)"
        requested = data.get("requested_package_name")
        lines = []
        if requested:
            lines.append(f"应用 {requested} 的使用时长:")
        else:
            lines.append(f"过去 {data.get('since_hours', '?')} 小时 Top {len(entries)} 应用使用时长:")
        for entry in entries:
            name = entry.get("app_name", "")
            pkg = entry.get("package_name", "")
            ms = entry.get("total_foreground_time_ms", 0)
            duration = self._format_duration(ms)
            lines.append(f"- {name} ({pkg}): {duration}")
        return "\n".join(lines)

    @staticmethod
    def _format_duration(ms: int) -> str:
        """毫秒转可读时长"""
        if ms <= 0:
            return "未使用"
        seconds = ms // 1000
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h}h {m}m"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"
