"""强制停止应用工具 (Shizuku 通道)"""

from pydantic import BaseModel, Field

from .base import DeviceToolBase


class ForceStopAppInput(BaseModel):
    package_name: str = Field(description="要强制停止的应用包名, 如 com.ss.android.ugc.aweme")


class ForceStopAppTool(DeviceToolBase):
    """强制停止指定应用 (需 Shizuku, 真正强停, 能停掉前台应用)"""

    name = "force_stop_app"
    description = (
        "强制停止手机上指定的应用。会通过 Shizuku 执行 am force-stop, "
        "能停掉前台运行的应用。若 Shizuku 未启用则降级为 killBackgroundProcesses "
        "(停不了前台应用, 应用可能立即重启)。仅 Master 可用。"
    )
    short_description = "强制停止手机应用 (仅 Master, 需 Shizuku)"
    args_schema = ForceStopAppInput

    async def _run(self, package_name: str = "") -> str:
        if not package_name.strip():
            return "请提供要停止的应用包名"
        return await self._execute(
            "force_stop_app",
            {"package_name": package_name.strip()},
            timeout=15.0,
        )

    def _format_success(self, data):
        package_name = data.get("package_name", "")
        channel = data.get("channel", "shizuku")
        msg = f"已强制停止应用: {package_name}"
        if channel == "kill_background":
            msg += " (降级模式, 应用可能立即重启, 建议开启 Shizuku 获得真正强停能力)"
        elif channel == "shizuku":
            msg += " (Shizuku 通道, 已真正强停)"
        return msg
