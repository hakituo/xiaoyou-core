# -*- coding: utf-8 -*-
"""HealthDataTool — 查询主人的手表健康数据

数据来自手机端 Samsung Health 同步(见 core.services.health_sync)。
按用户要求走工具调用而非 prompt 注入,避免每轮对话都塞一堆健康字段浪费 token。

两种查询模式:
- ``now``      当前快照:心率、步数、睡眠、体重等最新值
- ``timeline`` 事件时间线:今天几点心率多少、几点喝了多少水、几点吃了什么
"""
from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("HealthDataTool")

# 快照里挑出来给 AI 看的字段(全量 50+ 字段会撑爆上下文)
_SNAPSHOT_FIELDS = {
    "heart_rate": "心率(bpm)",
    "heart_rate_timestamp": "心率测量时间",
    "steps_today": "今日步数",
    "steps": "步数",
    "total_distance_km": "今日距离(km)",
    "active_time_minutes": "今日活动时长(分钟)",
    "active_calories_burned": "今日活动消耗(kcal)",
    "floors_climbed": "今日爬楼层数",
    "sleep_minutes": "昨晚睡眠时长(分钟)",
    "sleep_start_time": "入睡时间",
    "sleep_end_time": "起床时间",
    "sleep_score": "睡眠得分",
    "sleep_stage_deep_minutes": "深睡时长(分钟)",
    "sleep_stage_rem_minutes": "REM时长(分钟)",
    "weight_kg": "体重(kg)",
    "height_m": "身高(m)",
    "body_fat_percent": "体脂率",
    "skeletal_muscle_mass": "骨骼肌量(kg)",
    "basal_metabolic_rate": "基础代谢(kcal)",
    "oxygen_saturation": "血氧",
    "blood_oxygen": "血氧(三星)",
    "skin_temperature": "皮肤温度(°C)",
    "body_temperature": "体温(°C)",
    "blood_pressure_systolic": "收缩压(mmHg)",
    "blood_pressure_diastolic": "舒张压(mmHg)",
    "blood_glucose": "血糖(mmol/L)",
    "water_intake_ml": "今日饮水(ml)",
    "nutrition_calories": "今日摄入热量(kcal)",
    "nutrition_protein": "今日蛋白质(g)",
    "nutrition_carbs": "今日碳水(g)",
    "nutrition_fat": "今日脂肪(g)",
    "nutrition_entries": "今日逐条饮食(食物名/餐次/热量/时间)",
    "water_intake_entries": "今日逐条饮水(时间/量ml)",
    "energy_score": "能量评分",
    "sleep_apnea_sign": "睡眠呼吸暂停征兆",
    "irregular_heart_rhythm": "心律不齐",
    "server_timestamp": "数据更新时间",
}

_VALID_EVENT_TYPES = (
    "heart_rate", "water", "meal", "steps",
    "sleep_start", "wake_up", "body", "vital", "health_alert",
)


class HealthDataInput(BaseModel):
    """健康数据查询参数"""

    mode: str = Field(
        "now",
        description="查询模式: now=当前快照(心率/步数/睡眠/体重等最新值), "
                    "timeline=事件时间线(几点心率多少/几点喝了多少水/几点吃了饭), "
                    "trend=体成分历史趋势(体重/体脂随时间变化)",
    )
    date: Optional[str] = Field(
        None, description="timeline 模式的日期 YYYY-MM-DD,缺省为今天"
    )
    types: Optional[str] = Field(
        None,
        description="timeline 模式的事件类型过滤,逗号分隔。可选: "
                    "heart_rate(心率) water(饮水) meal(进食:逐条食物名+完整营养素) steps(步数里程碑) "
                    "sleep_start(入睡) wake_up(起床) body(体重体脂) "
                    "vital(血压血糖体温血氧) health_alert(健康预警)",
    )
    limit: int = Field(50, description="timeline/trend 模式最多返回多少条记录")


class HealthDataTool(BaseTool):
    name = "query_health_data"
    description = (
        "查询主人手表(Samsung Health)同步上来的健康数据。"
        "想知道他现在心率多少、今天走了多少步、昨晚睡得好不好、体重多少,用 mode=now;"
        "想知道今天几点心率多少、几点喝了多少水、几点吃的饭,用 mode=timeline;"
        "想看体重/体脂的历史变化趋势(最近在增重还是减脂),用 mode=trend。"
        "关心他身体状况、劝他喝水休息、聊作息之前,可以先查一下。"
        "注意: 返回的 nutrition_entries(逐条饮食)里除热量/蛋白/碳水/脂肪外, "
        "还带完整营养素——膳食纤维(dietary_fiber)、糖(sugar)、胆固醇(cholesterol)、"
        "钠(sodium)、钾(potassium)、维生素A(vitamin_a)、维生素C(vitamin_c)、"
        "钙(calcium)、铁(iron)等(均有值才返回)。当用户问'吃了什么/营养健不健康/"
        "营养够不够'时, 应把这几项一起报出来, 而不只是蛋白碳水脂肪。"
    )
    short_description = "查询手表健康数据(心率/睡眠/步数/饮水/体重/营养)"
    args_schema = HealthDataInput
    category = "life"
    enabled_by_default = True

    async def _run(
        self,
        mode: str = "now",
        date: Optional[str] = None,
        types: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """执行健康数据查询"""
        try:
            from core.services.health_sync.store import (
                read_daily_nutrition,
                read_events,
                read_latest,
            )
            from core.utils.time_utils import today_str

            mode = (mode or "now").strip().lower()

            if mode == "trend":
                # 体成分历史趋势(体重/体脂随时间变化)
                from core.services.health_sync.store import read_body_history

                history = read_body_history(limit=limit)
                if not history:
                    return json.dumps(
                        {"message": "还没有体成分历史记录(体重/体脂可能还没同步过)"},
                        ensure_ascii=False,
                    )
                return json.dumps(
                    {"count": len(history), "records": history},
                    ensure_ascii=False,
                )

            if mode == "timeline":
                type_list = None
                if types:
                    type_list = [
                        t.strip() for t in types.split(",")
                        if t.strip() in _VALID_EVENT_TYPES
                    ] or None

                events = read_events(date_str=date, limit=limit, types=type_list)
                # 按日期带上逐条饮食/饮水明细, 否则 AI 在 timeline 里只看得到
                # 聚合 kcal 而看不到具体食物名(用户反馈: "只看得到kcal看不到食品")。
                # 用 date 而非 latest.json, 这样查"昨天/前天吃了什么"也能拿到食物名。
                extra: Dict[str, Any] = {}
                snap = read_daily_nutrition(date or today_str())
                if snap:
                    for key in ("nutrition_entries", "water_intake_entries"):
                        if snap.get(key):
                            extra[key] = snap[key]
                # 关键: meal 事件依赖 nutrition_calories 的增量判断(delta>0才生成),
                # 跨天重置/热量不变时 meal 事件往往为空, 但 nutrition/<date>.json 里
                # 明明有饮食明细。因此只要 nutrition 文件里有"吃了什么", 即使 events
                # 为空也不能直接说"没有记录", 否则 AI 永远查不到当天进食(用户反馈:
                # "他查了 timeline 的 meal 还是空的")。
                if not events and not extra:
                    return json.dumps(
                        {"message": "这段时间没有健康事件记录(可能手表没同步)"},
                        ensure_ascii=False,
                    )
                payload: Dict[str, Any] = {
                    "date": date or "今天",
                    "count": len(events),
                    "events": events,
                }
                payload.update(extra)
                return json.dumps(payload, ensure_ascii=False)

            # 默认 now 模式:返回当前快照
            snapshot = read_latest()
            if not snapshot:
                return json.dumps(
                    {"message": "还没有手表健康数据(手机端可能未授权 Samsung Health)"},
                    ensure_ascii=False,
                )

            result = {
                label: snapshot[key]
                for key, label in _SNAPSHOT_FIELDS.items()
                if snapshot.get(key) is not None
            }
            if not result:
                return json.dumps({"message": "健康数据为空"}, ensure_ascii=False)

            # 同时带上今日逐条饮食/饮水明细, 让 AI 能看到"吃了什么"而不是只有
            # 聚合 kcal(用户反馈: "只记了午饭(爸爸做的), 具体吃了啥一个字没有")。
            # 注意用今天(本地时区)去 nutrition 分桶里查, 与 _entry_date 的本地化一致。
            day_snap = read_daily_nutrition(today_str())
            if day_snap:
                for key in ("nutrition_entries", "water_intake_entries"):
                    if day_snap.get(key):
                        result[key] = day_snap[key]
            return json.dumps(result, ensure_ascii=False)

        except Exception as e:
            logger.error(f"健康数据查询失败: {e}")
            return json.dumps({"error": f"查询失败: {e}"}, ensure_ascii=False)
