"""启动应用工具"""

from typing import Optional

from pydantic import BaseModel, Field

from .base import DeviceToolBase


class StartAppInput(BaseModel):
    package_name: str = Field(description="要启动的应用包名")
    activity: Optional[str] = Field(
        default=None,
        description="可选, 指定启动的 Activity 类名 (全限定名), 不填则用默认启动器",
    )


class StartAppTool(DeviceToolBase):
    """启动手机上的应用"""

    name = "start_app"
    description = (
        "启动手机上指定的应用。可只提供包名用默认启动器打开, "
        "也可指定 activity 精确启动某个 Activity。仅 Master 可用。"
    )
    short_description = "启动手机应用 (仅 Master)"
    args_schema = StartAppInput

    async def _run(
        self, package_name: str = "", activity: Optional[str] = None
    ) -> str:
        if not package_name.strip():
            return "请提供要启动的应用包名"
        args = {"package_name": package_name.strip()}
        if activity and activity.strip():
            args["activity"] = activity.strip()
        return await self._execute("start_app", args, timeout=10.0)

    def _format_success(self, data):
        package_name = data.get("package_name", "")
        activity = data.get("activity", "")
        if activity:
            return f"已启动应用: {package_name} (Activity: {activity})"
        return f"已启动应用: {package_name}"
