#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户生理数据记录工具"""

from typing import Optional, Type
from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.services.workspace.status_manager import get_user_status_manager
from core.services.user_physiology.service import get_user_physiology_service


class RecordBodyMetricsInput(BaseModel):
    weight_kg: Optional[float] = Field(default=None, description="体重（kg）")
    body_fat_percent: Optional[float] = Field(default=None, description="体脂率（%）")
    muscle_mass_kg: Optional[float] = Field(default=None, description="肌肉量（kg）")
    bmi: Optional[float] = Field(default=None, description="BMI 指数")
    note: Optional[str] = Field(default=None, description="备注说明")


class RecordBodyMetricsTool(BaseTool):
    name = "record_body_metrics"
    description = "记录用户的体质数据（体重、体脂率、肌肉量等）。当用户报告身体测量数据时使用。"
    args_schema: Type[BaseModel] = RecordBodyMetricsInput

    async def _run(
        self,
        weight_kg: Optional[float] = None,
        body_fat_percent: Optional[float] = None,
        muscle_mass_kg: Optional[float] = None,
        bmi: Optional[float] = None,
        note: Optional[str] = None,
    ) -> str:
        # 1. 更新 status_manager 中的体重数据
        status_mgr = get_user_status_manager()
        if weight_kg is not None:
            status_mgr.set_weight_kg(weight_kg)

        # 2. 更新 user_physiology 中的完整生理数据
        physiology = get_user_physiology_service()
        metrics = {}
        if weight_kg is not None:
            metrics["weight_kg"] = weight_kg
        if body_fat_percent is not None:
            metrics["body_fat_percent"] = body_fat_percent
        if muscle_mass_kg is not None:
            metrics["muscle_mass_kg"] = muscle_mass_kg
        if bmi is not None:
            metrics["bmi"] = bmi

        if metrics:
            physiology.update("default_user", {"metrics": metrics, "source": "user_input"})

        # 3. 返回确认信息
        parts = []
        if weight_kg is not None:
            parts.append(f"体重：{weight_kg:.1f}kg")
        if body_fat_percent is not None:
            parts.append(f"体脂率：{body_fat_percent:.1f}%")
        if muscle_mass_kg is not None:
            parts.append(f"肌肉量：{muscle_mass_kg:.1f}kg")
        if bmi is not None:
            parts.append(f"BMI: {bmi:.1f}")

        result = f"已记录体质数据：{', '.join(parts)}"
        if note:
            result += f"\n备注：{note}"

        return result
