"""获取手机设备位置工具 (原生 LocationManager 通道)

与 PhoneActionExecutor.GetLocation (用 FusedLocationProviderClient, 依赖 Google Play 服务) 不同,
本工具走 device_command 通道, 前端用 Android 原生 LocationManager 实现, 不依赖 Google Play 服务。

适用场景: Master 想知道用户当前在哪儿 (如主动关怀时判断"是否在外面/在回家路上")。
"""

from pydantic import BaseModel, Field

from .base import DeviceToolBase


class GetDeviceLocationInput(BaseModel):
    high_accuracy: bool = Field(
        default=True,
        description=(
            "True 优先用 GPS_PROVIDER 获取高精度位置 (可能慢, 需室外 GPS 信号)。"
            "False 用 NETWORK_PROVIDER 获取粗略位置 (基于基站/Wi-Fi, 快但精度低, 室内可用)。"
        ),
    )
    timeout_seconds: int = Field(
        default=15,
        description="等待位置的最大秒数, 超时返回最后已知位置或失败。建议 10-30。",
    )


class GetDeviceLocationTool(DeviceToolBase):
    """获取手机设备的地理位置 (原生 LocationManager, 不依赖 Google Play 服务)"""

    name = "get_device_location"
    description = (
        "获取手机当前的地理位置 (经纬度)。通过 Android 原生 LocationManager 实现, "
        "不依赖 Google Play 服务, 兼容无 GMS 的设备 (如华为/小米国行)。"
        "high_accuracy=True 用 GPS (室外精度高, 慢), False 用 NETWORK (室内可用, 快但粗略)。"
        "仅 Master 可用。"
    )
    short_description = "获取手机地理位置 (原生 LocationManager, 仅 Master)"
    args_schema = GetDeviceLocationInput

    async def _run(
        self,
        high_accuracy: bool = True,
        timeout_seconds: int = 15,
    ) -> str:
        safe_timeout = max(5, min(int(timeout_seconds), 60))
        return await self._execute(
            "get_device_location",
            {
                "high_accuracy": bool(high_accuracy),
                "timeout_seconds": safe_timeout,
            },
            timeout=float(safe_timeout) + 5.0,  # 给前端留点余量
        )

    def _format_success(self, data) -> str:
        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is None or lon is None:
            return f"获取位置成功但数据不完整: {data}"

        accuracy = data.get("accuracy_meters")
        provider = data.get("provider", "unknown")
        timestamp = data.get("timestamp_ms", 0)

        parts = [f"位置: 纬度 {lat}, 经度 {lon}"]
        if accuracy is not None:
            parts.append(f"精度 ±{accuracy:.0f} 米")
        parts.append(f"来源: {provider}")

        # 附带可读地址 (如果前端反地理了)
        address = data.get("address")
        if address:
            parts.append(f"地址: {address}")

        # 时间戳转可读
        if timestamp:
            import time

            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp / 1000))
            parts.append(f"定位时间: {ts_str}")

        return " | ".join(parts)
