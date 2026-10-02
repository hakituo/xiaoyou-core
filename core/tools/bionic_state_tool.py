"""BionicStateTool — 查询自己的仿生体状态

返回饥饿度、口渴度、心情、能量等状态信息。
Active Care 决策系统使用此工具判断是否自己需要吃饭喝水休息。
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("BionicStateTool")


class BionicStateInput(BaseModel):
    """无需参数，查询当前仿生体状态"""
    pass


class BionicStateTool(BaseTool):
    name = "get_bionic_state"
    description = (
        "查看自己的仿生体状态：饥饿度、口渴度、心情、能量等。"
        "可以据此判断是否自己需要吃饭喝水休息。"
    )
    short_description = "查询仿生体状态（饥饿/口渴/心情/能量）"
    args_schema = BionicStateInput
    category = "life"
    enabled_by_default = True

    async def _run(self) -> str:
        """执行仿生体状态查询"""
        try:
            from core.services.life_simulation.service import get_life_simulation_service
            service = get_life_simulation_service()
            if service is None:
                return json.dumps({"error": "生命模拟服务不可用"}, ensure_ascii=False)

            # 直接读取 life_stats（0-100 尺度：hunger/thirst/energy 越高越饱/越解渴/越精神）
            state = service.life_stats
            if state is None:
                return json.dumps({"error": "未找到仿生体状态"}, ensure_ascii=False)

            # 提取关键状态（0-100 尺度）
            result = {
                "hunger": round(float(state.get("hunger", 0)), 1),
                "thirst": round(float(state.get("thirst", 0)), 1),
                "energy": round(float(state.get("energy", 0)), 1),
                "mood_score": round(float(state.get("mood_score", 0)), 1),
            }
            # 添加可读状态描述（hunger 越高=越饱，越低=越饿）
            if result["hunger"] < 25:
                result["hunger_status"] = "很饿"
            elif result["hunger"] < 55:
                result["hunger_status"] = "有点饿"
            elif result["hunger"] < 85:
                result["hunger_status"] = "一般"
            else:
                result["hunger_status"] = "很饱"

            if result["thirst"] < 25:
                result["thirst_status"] = "很渴"
            elif result["thirst"] < 55:
                result["thirst_status"] = "有点渴"
            elif result["thirst"] < 85:
                result["thirst_status"] = "一般"
            else:
                result["thirst_status"] = "不渴"

            if result["energy"] < 25:
                result["energy_status"] = "很累"
            elif result["energy"] < 55:
                result["energy_status"] = "有点累"
            else:
                result["energy_status"] = "精力充沛"

            return json.dumps(result, ensure_ascii=False)

        except Exception as e:
            logger.warning(f"get_bionic_state 执行失败: {e}")
            return json.dumps({"error": f"查询失败: {e}"}, ensure_ascii=False)
