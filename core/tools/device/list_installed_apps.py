"""列出已安装应用工具"""

from pydantic import BaseModel, Field

from .base import DeviceToolBase


class ListInstalledAppsInput(BaseModel):
    include_system_apps: bool = Field(
        default=False,
        description="是否包含系统应用, 默认 false 只列用户安装的应用",
    )
    limit: int = Field(
        default=100,
        description="最多返回的应用数量, 默认 100",
    )


class ListInstalledAppsTool(DeviceToolBase):
    """列出手机上已安装的应用"""

    name = "list_installed_apps"
    description = (
        "列出手机上已安装的应用列表。默认只返回用户安装的应用 (不含系统应用), "
        "按应用名排序。可指定 include_system_apps=true 包含系统应用, "
        "limit 限制返回数量。仅 Master 可用。"
    )
    short_description = "列出手机已安装应用 (仅 Master)"
    args_schema = ListInstalledAppsInput

    async def _run(
        self, include_system_apps: bool = False, limit: int = 100
    ) -> str:
        safe_limit = max(1, min(int(limit or 100), 500))
        return await self._execute(
            "list_installed_apps",
            {
                "include_system_apps": bool(include_system_apps),
                "limit": safe_limit,
            },
            timeout=15.0,
        )

    def _format_success(self, data):
        apps = data.get("apps", [])
        if not apps:
            return "手机上没有匹配的应用"
        lines = [f"共 {len(apps)} 个应用:"]
        for app in apps[:200]:  # 限制输出长度
            name = app.get("name", "")
            pkg = app.get("package_name", "")
            lines.append(f"- {name} ({pkg})")
        return "\n".join(lines)
