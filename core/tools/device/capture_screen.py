"""手机截图工具

和电脑端 look_at_screen (screen_capture_tool) 对应, 但截图手机屏幕。
后端下发指令 → 手机端截图 → 回传 base64 → 后端调 VisionModule 分析 → 返回结果给 LLM。
"""

import base64
import os
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from core.tools.device.base import DeviceToolBase
from core.utils.logger import get_logger

logger = get_logger("device_capture_screen_tool")

# 截图保存目录 (companion_data 已在 .gitignore)
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_SCREENSHOT_DIR = os.path.join(
    _PROJECT_ROOT, "companion_data", "temp", "mobile_screen_captures"
)

# 调用冷却, 避免 AI 频繁截图浪费视觉模型 token
_COOLDOWN_SECONDS = 30.0
_last_capture_ts = 0.0


class CaptureScreenInput(BaseModel):
    question: Optional[str] = Field(
        default=None,
        description=(
            "想了解手机屏幕上的什么内容, 例如「用户在玩什么游戏」"
            "「在看什么视频」「在聊什么」。不填则默认分析「用户当前在做什么」。"
        ),
    )


class CaptureScreenTool(DeviceToolBase):
    """截图手机屏幕并用视觉模型分析"""

    name = "capture_phone_screen"
    description = (
        "截图手机当前屏幕并用视觉模型分析, 了解用户在手机上做什么。"
        "需要手机端已连接后端并在线。"
        "可在用户询问「我在干嘛」或主动关怀时调用。仅 Master 可用, 有 30 秒冷却。"
    )
    short_description = "截图并分析手机屏幕 (仅 Master)"
    args_schema = CaptureScreenInput

    async def _run(self, question: Optional[str] = None) -> str:
        global _last_capture_ts
        now = time.time()
        left = _COOLDOWN_SECONDS - (now - _last_capture_ts)
        if left > 0:
            return f"手机截图冷却中, 请 {left:.0f} 秒后再试"

        if not self._is_master():
            return "权限不足: 设备控制工具仅 Master 可用"

        # 下发截图指令到手机端
        result = await self._execute_raw("capture_screen", {}, timeout=20.0)
        _last_capture_ts = now

        if result.get("status") != "success":
            error = result.get("error", "未知错误")
            return f"手机截图失败: {error}"

        data = result.get("result", {})
        if not isinstance(data, dict):
            return "手机截图失败: 结果格式异常"
        image_base64 = data.get("image_base64")
        if not image_base64:
            return "手机截图失败: 未返回图片数据"

        # 保存截图到本地
        try:
            os.makedirs(_SCREENSHOT_DIR, exist_ok=True)
            file_name = (
                f"mobile_{time.strftime('%Y%m%d_%H%M%S')}"
                f"_{int(time.time() * 1000) % 1000:03d}.jpg"
            )
            file_path = os.path.join(_SCREENSHOT_DIR, file_name)
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(image_base64))
        except Exception as e:
            logger.error("保存手机截图失败: %s", e, exc_info=True)
            return f"截图已收到但保存失败: {e}"

        # 调用视觉模型分析
        q = (question or "").strip()
        if q:
            prompt = (
                f"这是一张用户手机屏幕的截图。请回答: {q}"
                "请基于截图内容给出具体、准确的回答, "
                "如果截图中有应用名称、网页标题、游戏画面等关键信息请一并说明。"
            )
        else:
            prompt = (
                "这是一张用户手机屏幕的截图。请描述用户当前在做什么, "
                "重点说明: (1) 用户在使用什么应用/游戏/网页; "
                "(2) 具体内容是什么 (如游戏名、视频标题、聊天对象等); "
                "(3) 用户的活动状态。请简洁准确地回答。"
            )

        try:
            from core.core_engine.service_singletons import get_vision_module

            vm = get_vision_module()
            if vm is None:
                return (
                    f"手机截图成功但视觉模块未初始化, 无法分析。截图路径: {file_path}"
                )
            vm_result = await vm.describe_image(file_path, prompt)
            if isinstance(vm_result, dict):
                if vm_result.get("status") == "success":
                    desc = (
                        vm_result.get("response")
                        or vm_result.get("description")
                        or ""
                    )
                    if desc:
                        return f"手机屏幕内容分析: {desc}"
                    return "视觉分析完成但未返回内容"
                return (
                    f"视觉分析失败: {vm_result.get('error', '未知错误')}"
                    f" (截图已保存: {file_path})"
                )
            return str(vm_result)
        except Exception as e:
            logger.error("视觉分析失败: %s", e, exc_info=True)
            return f"截图成功但视觉分析失败: {e}。截图路径: {file_path}"

    async def _execute_raw(
        self,
        command: str,
        args: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """直接调 bridge 拿原始结果 dict (不走基类 _execute 的字符串化)"""
        user_id = self._get_ctx("user_id")
        from core.services.device_command import get_device_command_bridge

        bridge = get_device_command_bridge()
        return await bridge.execute(command, args, user_id, timeout=timeout)
