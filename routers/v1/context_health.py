# -*- coding: utf-8 -*-
"""健康数据同步子路由。

从 routers.v1.context 解耦,专门处理 Health Connect / 穿戴设备同步上来的健康数据。

存储策略见 core.services.health_sync.store:
- 快照覆盖写 latest.json(回答"现在怎么样")
- 变化点追加写 events/YYYY-MM-DD.jsonl(回答"今天几点心率多少/喝了多少水")

检测到起床(sleep_end_time 更新)时联动退出 Active Care 低打扰模式。
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode, get_friendly_error_message
from core.services.health_sync.store import ingest_snapshot, read_events, read_latest
from core.services.health_sync.wakeup import exit_quiet_mode_on_wakeup
from core.utils.time_utils import now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/context/health", tags=["健康数据"])


class HealthSyncRequest(BaseModel):
    """健康数据同步请求(前端传什么存什么,用于探索可用字段)。

    支持数据来源:
    - wear_os: 手表端 Health Services 实时数据
    - health_connect: Health Connect 历史数据(国行不可用)
    - samsung_health: Samsung Health Data SDK 全量数据(国行替代方案)

    注意: 手机端分档同步,高频通道只上报心率等少数字段,其余为 None。
    None 表示"本次没读取",不会覆盖 latest.json 里的已有值。
    """

    # ===== 基础字段(wear_os / health_connect / samsung_health 共用) =====
    steps: Optional[int] = Field(None, description="今日步数(手表实时)")
    heart_rate: Optional[int] = Field(None, description="最新心率 bpm")
    heart_rate_timestamp: Optional[str] = Field(
        None, description="心率测量时间 ISO-8601"
    )
    weight_kg: Optional[float] = Field(None, description="体重 kg")
    weight_timestamp: Optional[str] = Field(None, description="体重测量时间 ISO-8601")
    height_m: Optional[float] = Field(None, description="身高 m")
    height_timestamp: Optional[str] = Field(None, description="身高测量时间 ISO-8601")
    body_fat_percent: Optional[float] = Field(None, description="体脂率 0-1")
    skeletal_muscle_percent: Optional[float] = Field(None, description="骨骼肌率 0-1")
    basal_metabolic_rate: Optional[int] = Field(None, description="基础代谢率 kcal")
    # 身体成分扩展字段(kg, Samsung Health BodyCompositionType 扩展)
    muscle_mass: Optional[float] = Field(None, description="肌肉量 kg")
    body_fat_mass: Optional[float] = Field(None, description="脂肪量 kg")
    fat_free_mass: Optional[float] = Field(None, description="去脂体重 kg")
    skeletal_muscle_mass: Optional[float] = Field(None, description="骨骼肌量 kg")
    total_body_water: Optional[float] = Field(None, description="总体水分 kg")
    sleep_minutes: Optional[int] = Field(None, description="睡眠时长分钟")
    sleep_start_time: Optional[str] = Field(None, description="睡眠开始时间 ISO-8601")
    sleep_end_time: Optional[str] = Field(None, description="睡眠结束时间 ISO-8601")
    # 睡眠阶段时长(Samsung Health SleepSession.stages)
    sleep_stage_awake_minutes: Optional[int] = Field(None, description="清醒阶段时长分钟")
    sleep_stage_light_minutes: Optional[int] = Field(None, description="浅睡阶段时长分钟")
    sleep_stage_deep_minutes: Optional[int] = Field(None, description="深睡阶段时长分钟")
    sleep_stage_rem_minutes: Optional[int] = Field(None, description="REM 阶段时长分钟")
    # 睡眠得分(0-100, SDK 字段 SLEEP_SCORE)
    sleep_score: Optional[int] = Field(None, description="睡眠得分 0-100")
    oxygen_saturation: Optional[float] = Field(None, description="血氧饱和度 0-1")
    oxygen_saturation_timestamp: Optional[str] = Field(
        None, description="血氧测量时间 ISO-8601"
    )
    calories_burned: Optional[float] = Field(None, description="消耗卡路里 kcal")
    blood_glucose: Optional[float] = Field(None, description="血糖 mmol/L")
    blood_pressure_systolic: Optional[float] = Field(None, description="收缩压 mmHg")
    blood_pressure_diastolic: Optional[float] = Field(None, description="舒张压 mmHg")
    body_temperature: Optional[float] = Field(None, description="体温 °C")
    collected_at: Optional[str] = Field(None, description="客户端采集时间 ISO-8601")
    source: Optional[str] = Field(
        None, description="数据来源 wear_os/health_connect/samsung_health"
    )

    # ===== Samsung Health 扩展字段(共 17 类) =====
    # 皮肤温度(三元组)
    skin_temperature: Optional[float] = Field(None, description="皮肤温度 °C")
    # 血氧(三元组,Samsung Health 独立字段,与 oxygen_saturation 同义但来源不同)
    blood_oxygen: Optional[float] = Field(None, description="血氧饱和度 0-1 (Samsung Health)")
    # 爬楼/饮水/营养
    floors_climbed: Optional[float] = Field(None, description="今日爬楼层数")
    water_intake_ml: Optional[float] = Field(None, description="今日饮水量 ml")
    nutrition_calories: Optional[float] = Field(None, description="今日摄入热量 kcal")
    nutrition_protein: Optional[float] = Field(None, description="今日蛋白质摄入 g")
    nutrition_carbs: Optional[float] = Field(None, description="今日碳水摄入 g")
    nutrition_fat: Optional[float] = Field(None, description="今日脂肪摄入 g")
    # 健康预警
    sleep_apnea_sign: Optional[str] = Field(None, description="睡眠呼吸暂停征兆枚举名")
    irregular_heart_rhythm: Optional[str] = Field(
        None, description="心律不齐通知状态枚举名"
    )
    # 能量评分
    energy_score: Optional[float] = Field(None, description="今日能量评分")
    # 今日活动聚合
    steps_today: Optional[int] = Field(None, description="今日总步数(聚合查询)")
    active_calories_burned: Optional[float] = Field(
        None, description="今日活动消耗热量 kcal"
    )
    total_calories_burned: Optional[float] = Field(
        None, description="今日总消耗热量 kcal"
    )
    active_time_minutes: Optional[int] = Field(None, description="今日活动时长分钟")
    total_distance_km: Optional[float] = Field(None, description="今日总距离 km")
    # 各类目标
    sleep_goal_bed_time: Optional[str] = Field(None, description="睡眠目标就寝时间 HH:MM")
    sleep_goal_wake_time: Optional[str] = Field(None, description="睡眠目标起床时间 HH:MM")
    steps_goal: Optional[int] = Field(None, description="步数目标")
    active_calories_goal: Optional[int] = Field(None, description="活动热量目标 kcal")
    active_time_goal_minutes: Optional[int] = Field(None, description="活动时长目标分钟")
    water_intake_goal_ml: Optional[float] = Field(None, description="饮水目标 ml")
    nutrition_goal_calories: Optional[float] = Field(None, description="热量摄入目标 kcal")

    # ===== 逐条明细(含食物名/餐次/时间) =====
    # 由手机端 SamsungHealthSnapshot.toSyncJson() 发出, 形如:
    # [{"title": "麦香鸡", "meal_name": "午餐", "calorie": 485.0,
    #   "date": "2026-08-07", "time": "12:30"}, ...]
    # 主键: (title, date, time), 覆盖写, 让 AI 能说出"你中午吃了麦香鸡"而不是只看 kcal。
    nutrition_entries: Optional[List[Dict[str, Any]]] = Field(
        None, description="今日逐条饮食明细(食物名/餐次/热量/时间)"
    )
    water_intake_entries: Optional[List[Dict[str, Any]]] = Field(
        None, description="今日逐条饮水明细(时间/量 ml)"
    )


@router.post("/sync", summary="同步穿戴设备健康数据")
async def sync_health_data(request: HealthSyncRequest):
    """接收手机端上报的健康快照。

    处理流程:
    1. 合并进 latest.json(None 字段不覆盖旧值)
    2. 与上次快照做差分,把有意义的变化写进当日事件流
    3. 若产生 wake_up 事件,联动退出 Active Care 低打扰模式
    """
    try:
        # exclude_none=True: 让 store 能区分"没读到"与"读到了 0"
        payload = request.model_dump(exclude_none=True)
        result = ingest_snapshot(payload)

        wake_up_result = None
        if result.wake_up:
            wake_up_result = await exit_quiet_mode_on_wakeup(result.wake_up)

        # 兜底：store 仅在 sleep_end_time「字段值变化」时才会 emit wake_up。
        # 但手表(尤其 Samsung Health)常在睡眠一结束就定稿 sleep_end_time，
        # 之后同步该值不再变化，导致 wake_up 永不触发、低打扰僵死。
        # 因此只要本次仍携带了一个晚于上次晚安时刻的 sleep_end_time，
        # 就直接尝试退出低打扰（内部已带 sleep_end_ts <= last_goodnight_ts 防重）。
        if wake_up_result is None or not wake_up_result.get("state_synced"):
            _sleep_end = payload.get("sleep_end_time")
            if _sleep_end:
                _wakeup_result = await exit_quiet_mode_on_wakeup(
                    {"sleep_end": _sleep_end, "sleep_start": payload.get("sleep_start_time")}
                )
                wake_up_result = _wakeup_result

        try:
            from core.services.dual_role.social_events import get_social_event_engine

            get_social_event_engine().record_health_events(
                result.events,
                learned_by="aveline",
                wake_sleep_kind=str((wake_up_result or {}).get("sleep_kind") or ""),
            )
        except Exception as social_e:
            logger.warning("健康生活事件写入室友共享池失败: %s", social_e)

        return success_response(
            data={
                "message": "健康数据已同步",
                "saved_path": result.saved_path,
                "events": result.events,
                "event_count": len(result.events),
                "wake_up": wake_up_result,
                "timestamp": now_iso(),
            }
        )
    except Exception as e:
        logger.error(f"health sync failed: {e}")
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message=get_friendly_error_message(e),
        )


@router.get("/sync/latest", summary="获取最新健康快照")
async def get_latest_health_sync():
    """返回 latest.json 当前快照,用于前端调试展示。"""
    try:
        data = read_latest()
        if not data:
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND,
                message="暂无同步的健康数据",
            )
        return success_response(
            data={
                "path": "health_sync/latest.json",
                "data": data,
                "timestamp": now_iso(),
            }
        )
    except Exception as e:
        logger.error(f"get latest health sync failed: {e}")
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message=get_friendly_error_message(e),
        )


@router.get("/events", summary="获取健康事件流")
async def get_health_events(
    date: Optional[str] = None,
    limit: int = 200,
    types: Optional[str] = None,
):
    """按日期返回健康事件时间线。

    Args:
        date: YYYY-MM-DD,缺省为今天
        limit: 最多返回条数(取最近的)
        types: 逗号分隔的事件类型过滤,如 heart_rate,water
    """
    try:
        type_list = [t.strip() for t in types.split(",") if t.strip()] if types else None
        events = read_events(date_str=date, limit=limit, types=type_list)
        return success_response(
            data={
                "date": date,
                "events": events,
                "count": len(events),
                "timestamp": now_iso(),
            }
        )
    except Exception as e:
        logger.error(f"get health events failed: {e}")
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message=get_friendly_error_message(e),
        )
