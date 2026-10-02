"""设备控制工具基类

提供:
- _is_master() 权限校验 (复用 screen_capture_tool 的判断逻辑)
- _execute() 封装 DeviceCommandBridge 调用 + 结果格式化
"""

from typing import Any, Dict

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("device_tools")


class DeviceToolBase(BaseTool):
    """设备控制工具基类, 所有 device 工具继承此类"""

    category = "device"
    # 设备控制类工具默认不启用, 仅 Master 可用
    enabled_by_default = True

    def _is_master(self) -> bool:
        """判断当前会话是否属于 Master

        判断规则:
        1. conversation_id 为 default / default_user → Master (本地默认会话)
        2. conversation_id 的 session 段 (__ 之前) 为 private_{MASTER_QQ_ID} → Master
        3. 其他情况 → 非 Master
        """
        cid = str(self._get_ctx("user_id") or "").strip().lower()
        if not cid:
            return False
        if cid in {"default", "default_user"}:
            return True
        # 取 session_id 段 (__ 之前)
        session_part = cid.split("__")[0]
        try:
            from clients.bots.qq.settings import MASTER_QQ_ID

            master_id = str(MASTER_QQ_ID or "").strip()
            if master_id and session_part == f"private_{master_id}":
                return True
        except Exception:
            # 非 QQ 部署环境, 回退: default 系列已判断, 其余视为非 Master
            pass
        return False

    async def _execute(
        self,
        command: str,
        args: Dict[str, Any],
        timeout: float = 30.0,
    ) -> str:
        """下发设备指令并格式化结果

        Args:
            command: 指令名 (如 "force_stop_app")
            args: 指令参数
            timeout: 超时秒数

        Returns:
            格式化的结果字符串 (给 LLM 看)
        """
        if not self._is_master():
            return "权限不足: 设备控制工具仅 Master 可用"

        user_id = self._get_ctx("user_id")

        from core.services.device_command import get_device_command_bridge

        bridge = get_device_command_bridge()
        result = await bridge.execute(command, args, user_id, timeout=timeout)

        status = result.get("status")
        if status == "success":
            data = result.get("result", {})
            return self._format_success(data)
        else:
            error = result.get("error", "未知错误")
            return f"执行失败: {error}"

    def _format_success(self, data: Dict[str, Any]) -> str:
        """格式化成功结果, 子类可覆盖以自定义输出"""
        summary = data.get("summary")
        if summary:
            return str(summary)
        return str(data)
