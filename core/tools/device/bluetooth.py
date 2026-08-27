"""蓝牙设备管理工具集

提供 4 个蓝牙工具:
- list_paired_bluetooth_devices: 列出已配对蓝牙设备 (含连接状态)
- scan_bluetooth_devices: 扫描附近蓝牙设备 (10s)
- pair_bluetooth_device: 配对蓝牙设备 (createBond, 触发系统弹窗)
- unpair_bluetooth_device: 取消配对 (removeBond, 会断开连接)

适用场景:
- AI 主动关怀: 检测到耳机摘下/连上 → 推断用户活动
- 用户问"我的耳机连了吗" → 查询 list_paired
- 帮用户找丢失的耳机 → scan
- 帮用户连新设备 → pair
- 断开有问题的设备 → unpair

权限: BLUETOOTH_CONNECT (Android 12+)
"""

from pydantic import BaseModel, Field

from .base import DeviceToolBase


# ── 列出已配对蓝牙设备 ─────────────────────────────────


class ListPairedBluetoothDevicesInput(BaseModel):
    include_connection_state: bool = Field(
        default=True,
        description="是否查询每个设备的连接状态 (BLE profile 查询, 略慢但有用)",
    )


class ListPairedBluetoothDevicesTool(DeviceToolBase):
    """列出已配对蓝牙设备及连接状态"""

    name = "list_paired_bluetooth_devices"
    description = (
        "列出手机已配对的蓝牙设备 (耳机/手环/音箱等), 可选查询每个设备当前的连接状态。"
        "用于回答「我的耳机连了吗」「我配对了哪些蓝牙设备」等问题。仅 Master 可用。"
    )
    short_description = "列出已配对蓝牙设备 (仅 Master)"
    args_schema = ListPairedBluetoothDevicesInput

    async def _run(self, include_connection_state: bool = True) -> str:
        return await self._execute(
            "list_paired_bluetooth_devices",
            {"include_connection_state": bool(include_connection_state)},
            timeout=10.0,
        )

    def _format_success(self, data) -> str:
        devices = data.get("devices", [])
        if not devices:
            return "当前没有已配对的蓝牙设备"

        lines = [f"已配对蓝牙设备共 {len(devices)} 个:"]
        for d in devices:
            name = d.get("name", "未知名称")
            addr = d.get("address", "")
            state = d.get("connection_state", "unknown")
            major_class = d.get("major_class", "")
            line = f"- {name} ({addr})"
            if major_class:
                line += f" [{major_class}]"
            if state and state != "unknown":
                line += f" - {state}"
            lines.append(line)
        return "\n".join(lines)


# ── 扫描附近蓝牙设备 ───────────────────────────────────


class ScanBluetoothDevicesInput(BaseModel):
    duration_seconds: int = Field(
        default=10,
        description="扫描时长 (秒), 建议 5-15。过短可能漏掉设备, 过长耗电。",
    )
    include_paired: bool = Field(
        default=False,
        description="是否在结果中包含已配对的设备 (True 则重复列出已配对的, False 则只列新发现的)",
    )


class ScanBluetoothDevicesTool(DeviceToolBase):
    """扫描附近可发现的蓝牙设备"""

    name = "scan_bluetooth_devices"
    description = (
        "扫描附近可被发现的蓝牙设备 (需要设备处于可发现模式)。"
        "用于帮用户找丢失的耳机/手环, 或在配对前确认设备存在。"
        "扫描过程中蓝牙会被占用, 已连接设备可能短暂断开。仅 Master 可用。"
    )
    short_description = "扫描附近蓝牙设备 (仅 Master)"
    args_schema = ScanBluetoothDevicesInput

    async def _run(self, duration_seconds: int = 10, include_paired: bool = False) -> str:
        safe_duration = max(3, min(int(duration_seconds), 30))
        return await self._execute(
            "scan_bluetooth_devices",
            {
                "duration_seconds": safe_duration,
                "include_paired": bool(include_paired),
            },
            timeout=float(safe_duration) + 5.0,
        )

    def _format_success(self, data) -> str:
        devices = data.get("devices", [])
        duration = data.get("duration_seconds", 0)
        if not devices:
            return f"扫描 {duration}s 未发现可发现的蓝牙设备 (注意: 目标设备需进入配对模式)"

        lines = [f"扫描 {duration}s 发现 {len(devices)} 个蓝牙设备:"]
        for d in devices:
            name = d.get("name", "未知名称")
            addr = d.get("address", "")
            rssi = d.get("rssi")
            already_paired = d.get("already_paired", False)
            line = f"- {name} ({addr})"
            if rssi is not None:
                # RSSI 越接近 0 信号越强
                quality = "强" if rssi > -50 else "中" if rssi > -70 else "弱"
                line += f" 信号{quality}({rssi}dBm)"
            if already_paired:
                line += " [已配对]"
            lines.append(line)
        return "\n".join(lines)


# ── 配对蓝牙设备 ───────────────────────────────────────


class PairBluetoothDeviceInput(BaseModel):
    address: str = Field(
        description="目标设备 MAC 地址 (如 00:11:22:33:44:55), 可从 scan_bluetooth_devices 结果获取",
    )


class PairBluetoothDeviceTool(DeviceToolBase):
    """配对蓝牙设备 (触发 createBond, 系统会弹配对确认框)"""

    name = "pair_bluetooth_device"
    description = (
        "与指定 MAC 地址的蓝牙设备配对 (调用 createBond, 系统会弹配对确认框)。"
        "用于帮用户连接新蓝牙设备。配对成功后系统通常会自动建立连接。仅 Master 可用。"
    )
    short_description = "配对蓝牙设备 (仅 Master)"
    args_schema = PairBluetoothDeviceInput

    async def _run(self, address: str = "") -> str:
        addr = address.strip()
        if not addr:
            return "请提供要配对的蓝牙设备 MAC 地址"
        return await self._execute(
            "pair_bluetooth_device",
            {"address": addr},
            timeout=20.0,
        )

    def _format_success(self, data) -> str:
        addr = data.get("address", "")
        name = data.get("name", "")
        bond_state = data.get("bond_state", "unknown")
        if name:
            return f"设备 {name} ({addr}) 配对状态: {bond_state}"
        return f"设备 {addr} 配对状态: {bond_state}"


# ── 取消配对蓝牙设备 ───────────────────────────────────


class UnpairBluetoothDeviceInput(BaseModel):
    address: str = Field(
        description="要取消配对的设备 MAC 地址 (如 00:11:22:33:44:55)",
    )


class UnpairBluetoothDeviceTool(DeviceToolBase):
    """取消配对蓝牙设备 (removeBond, 会自动断开连接)"""

    name = "unpair_bluetooth_device"
    description = (
        "取消与指定蓝牙设备的配对 (调用 removeBond, 会自动断开连接)。"
        "用于断开有问题的设备, 或重置配对关系。仅 Master 可用。"
    )
    short_description = "取消配对蓝牙设备 (仅 Master)"
    args_schema = UnpairBluetoothDeviceInput

    async def _run(self, address: str = "") -> str:
        addr = address.strip()
        if not addr:
            return "请提供要取消配对的蓝牙设备 MAC 地址"
        return await self._execute(
            "unpair_bluetooth_device",
            {"address": addr},
            timeout=10.0,
        )

    def _format_success(self, data) -> str:
        addr = data.get("address", "")
        success = data.get("removed", False)
        if success:
            return f"已取消配对: {addr}"
        return f"取消配对失败: {addr} (可能本来就没配对)"
