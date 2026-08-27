# -*- coding: utf-8 -*-
"""设备上下文同步子路由。

从 routers.v1.context 解耦,专门处理设备上下文、应用使用统计、通知等数据的同步。
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.utils.data_paths import (
    get_companion_data_dir,
    get_user_daily_dir,
    get_user_latest_device_context_file,
)
from core.utils.time_utils import get_current_time, now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/context", tags=["设备上下文"])

_DAILY_DATA_BASE_DIR = get_companion_data_dir()


# ==================== 数据模型 ====================


class DeviceContext(BaseModel):
    device_id: str = Field(..., description="设备唯一标识")
    timestamp: float = Field(..., description="客户端时间戳")
    battery_level: Optional[float] = Field(None, description="电量 0.0-1.0")
    is_charging: Optional[bool] = Field(None, description="是否正在充电")
    network_type: Optional[str] = Field(None, description="网络类型 wifi/cellular/none")
    app_state: Optional[str] = Field(None, description="应用状态 active/background")
    current_app: Optional[str] = Field(None, description="当前前台应用包名")
    usage_stats: Optional[list] = Field(None, description="应用使用时长统计")
    step_count: Optional[int] = Field(None, description="今日步数")
    ambient_light_lux: Optional[float] = Field(None, description="环境光照强度")
    is_sleeping: Optional[bool] = Field(None, description="推断是否处于睡眠状态")
    recent_notifications: Optional[list] = Field(None, description="最近通知列表")
    location: Optional[dict] = Field(None, description="位置信息")
    extra: Optional[dict] = Field(default_factory=dict, description="扩展数据")


class AppUsageDto(BaseModel):
    package_name: str
    app_name: str
    usage_time_ms: int
    last_used_time: Optional[str] = None
    launch_count: int


class NotificationDto(BaseModel):
    id: str
    package_name: str
    app_name: str
    title: Optional[str] = None
    text: Optional[str] = None
    timestamp: str
    category: Optional[str] = None


class HealthDataDto(BaseModel):
    id: str
    type: str
    json_data: str
    timestamp: str


class ContextSyncRequest(BaseModel):
    device_context: dict
    app_usage: list[AppUsageDto] = Field(default_factory=list)
    notifications: list[NotificationDto] = Field(default_factory=list)
    health_data: list[HealthDataDto] = Field(default_factory=list)
    usage_window_start: Optional[str] = None
    usage_source: Optional[str] = None
    collected_at: str


# ==================== 辅助函数 ====================


def _ensure_daily_dir() -> Path:
    now_dt = get_current_time()
    daily_dir = (
        get_user_daily_dir()
        / now_dt.strftime("%Y")
        / now_dt.strftime("%m")
        / now_dt.strftime("%d")
    )
    daily_dir.mkdir(parents=True, exist_ok=True)
    return daily_dir


async def _write_device_context(entry: dict):
    import aiofiles

    daily_dir = _ensure_daily_dir()
    log_file = daily_dir / "device_context.jsonl"
    entry["server_timestamp"] = now_iso()
    async with aiofiles.open(log_file, mode="a", encoding="utf-8") as f:
        await f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    latest_file = get_user_latest_device_context_file()
    async with aiofiles.open(latest_file, mode="w", encoding="utf-8") as f:
        await f.write(json.dumps(entry, ensure_ascii=False))


# ==================== 设备上下文同步 ====================


@router.post("/sync", summary="同步设备上下文（综合）")
async def sync_context(request: ContextSyncRequest):
    try:
        daily_dir = _ensure_daily_dir()
        import aiofiles

        if request.device_context:
            await _write_device_context(request.device_context.copy())

        if request.notifications:
            notif_file = daily_dir / "notifications.jsonl"
            async with aiofiles.open(notif_file, mode="a", encoding="utf-8") as f:
                for notif in request.notifications:
                    n_dict = notif.model_dump()
                    n_dict["server_timestamp"] = now_iso()
                    await f.write(json.dumps(n_dict, ensure_ascii=False) + "\n")

        if request.health_data:
            health_file = daily_dir / "health_data.jsonl"
            async with aiofiles.open(health_file, mode="a", encoding="utf-8") as f:
                from core.services.workspace.status_manager import (
                    get_user_status_manager,
                )

                manager = get_user_status_manager()
                for hd in request.health_data:
                    hd_dict = hd.model_dump()
                    hd_dict["server_timestamp"] = now_iso()
                    await f.write(json.dumps(hd_dict, ensure_ascii=False) + "\n")
                    try:
                        parsed_data = json.loads(hd.json_data)
                        if hd.type == "body_metrics":
                            weight = parsed_data.get("weight")
                            if (
                                weight
                                and isinstance(weight, (int, float))
                                and weight > 0
                            ):
                                await asyncio.to_thread(
                                    manager.set_weight_kg, float(weight)
                                )
                    except Exception as he:
                        logger.warning(f"解析健康数据失败: {he}")

        # 应用使用时长: 数字健康(限额/强制退出)功能依赖它做 nightly 复盘。
        # DataSyncWorker 每 15 分钟上报一次, 同一天会有多条; 读取侧按
        # (package_name, server_timestamp 所在日) 取最新一条即可还原当日累计。
        if request.app_usage:
            usage_file = daily_dir / "app_usage.jsonl"
            sync_server_ts = now_iso()
            usage_report_trusted = _is_trusted_today_usage_report(
                usage_source=request.usage_source,
                usage_window_start=request.usage_window_start,
                server_timestamp=sync_server_ts,
            )
            async with aiofiles.open(usage_file, mode="a", encoding="utf-8") as f:
                for au in request.app_usage:
                    au_dict = au.model_dump()
                    au_dict["server_timestamp"] = sync_server_ts
                    au_dict["usage_source"] = request.usage_source
                    au_dict["usage_window_start"] = request.usage_window_start
                    await f.write(json.dumps(au_dict, ensure_ascii=False) + "\n")

            # 数字健康: 手机在线同步时, 若发现今日已超限则补一条 active care 关怀消息。
            # (真正的强制退出由 Android 端本地 Worker 完成, 这里仅作有人情味的提醒)
            try:
                from core.services.digital_wellbeing.service import (
                    get_wellbeing_service,
                )

                wb = get_wellbeing_service()
                today_str = get_current_time().strftime("%Y-%m-%d")
                # 聚合本次上报为 usable 结构, 避免重复读盘
                agg: Dict[str, dict] = {}
                for au in request.app_usage:
                    pkg = au.package_name
                    ms = int(au.usage_time_ms or 0)
                    st = sync_server_ts  # 统一用当前时间戳, 用于后续按最新聚合
                    # 同步侧同样丢弃 24h 滚动窗口/历史脏数据, 避免误触发 active care "超限"
                    cand = {
                        "package_name": pkg,
                        "usage_time_ms": ms,
                        "last_used_time": au.last_used_time,
                        "server_timestamp": st,
                        "usage_source": request.usage_source,
                        "usage_window_start": request.usage_window_start,
                    }
                    if not usage_report_trusted:
                        continue
                    if not _is_plausible_today_usage(cand):
                        continue
                    if pkg not in agg or st > agg[pkg].get("_ts", ""):
                        agg[pkg] = {
                            "package_name": pkg,
                            "app_name": au.app_name,
                            "usage_time_ms": ms,
                            "launch_count": getattr(au, "launch_count", 0) or 0,
                            "last_used_time": au.last_used_time,
                            "_ts": st,
                        }
                if not usage_report_trusted:
                    logger.warning(
                        "数字健康: 跳过不可信用量口径的超限关怀 source=%s window_start=%s",
                        request.usage_source or "legacy",
                        request.usage_window_start or "missing",
                    )
                asyncio.create_task(
                    wb.maybe_notify_exceeded_via_active_care(
                        target_date=today_str,
                        usage=list(agg.values()),
                    )
                )
            except Exception as ne:
                logger.warning(f"数字健康超限检查失败: {ne}")

        # 数字健康: 把"今日 + 明日"的限额随同步响应下发给 Android,
        # Android 本地定时检查超限并强制退出。
        # 修复: 今日优先 —— today 的限额才是"今天的限额", 必须优先采用;
        # next_day 仅在 today 无限额时兜底 (用户今天通过 LLM 工具改限额默认存明天,
        # 此时 next_day 代表用户最新意图, 对今天也生效)。
        # 原实现 for d in (today, next_day) 让 next_day 覆盖 today, 会把"明天的
        # 预测限额"当成"今天的限额", 若 next_day < today 用量则误判超限。
        app_limits: Dict[str, int] = {}
        try:
            from core.services.digital_wellbeing.service import get_wellbeing_service

            wb = get_wellbeing_service()
            today_str = get_current_time().strftime("%Y-%m-%d")
            import datetime

            next_day_str = (
                get_current_time().date() + datetime.timedelta(days=1)
            ).strftime("%Y-%m-%d")
            # 先读 next_day 兜底, 再用 today 覆盖, 保证 today 优先
            for d in (next_day_str, today_str):
                limits_data = wb.get_limits(d)
                for pkg, cfg in limits_data.get("limits", {}).items():
                    lm = int(cfg.get("limit_ms", 0) or 0)
                    if lm > 0:
                        app_limits[pkg] = lm
        except Exception as le:
            logger.warning(f"读取下发限额失败: {le}")

        # 数字健康: 下发"会话限额"(一次性 cap)。会话 cap 当天生效, 只读今天的,
        # 手机端据此在本地记录会话激活并做双重判断。
        session_caps: Dict[str, int] = {}
        try:
            from core.services.digital_wellbeing.service import get_wellbeing_service

            wb = get_wellbeing_service()
            today_str = get_current_time().strftime("%Y-%m-%d")
            limits_data = wb.get_limits(today_str)
            for pkg, cfg in limits_data.get("limits", {}).items():
                sc = int(cfg.get("session_cap_ms", 0) or 0)
                if sc > 0:
                    session_caps[pkg] = sc
        except Exception as sce:
            logger.warning(f"读取下发会话限额失败: {sce}")

        return {
            "status": "success",
            "message": "Context sync completed",
            "app_limits": app_limits,
            "session_caps": session_caps,
        }
    except Exception as e:
        logger.error(f"Failed to sync context: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/device", summary="上传设备上下文（单条）")
async def upload_device_context(context: DeviceContext):
    try:
        entry = context.model_dump()
        await _write_device_context(entry)
        try:
            from core.core_engine.event_bus import get_event_bus

            await get_event_bus().publish("device.context_updated", context=entry)
        except Exception as e:
            logger.warning(f"Failed to publish device context event: {e}")
        return {"status": "success", "message": "Context saved"}
    except Exception as e:
        logger.error(f"Failed to save device context: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 数字健康: 用量合理性护栏 ====================

_TRUSTED_USAGE_SOURCE = "android_today_since_midnight_v1"
_USAGE_WINDOW_TOLERANCE_SECONDS = 5 * 60


def _parse_dt_preserve_timezone(s: Optional[str]):
    """解析 ISO 时间并保留原始时区；无时区值按服务端本地时区解释。"""
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            local_tz = get_current_time().tzinfo or timezone.utc
            dt = dt.replace(tzinfo=local_tz)
        return dt
    except Exception:
        return None


def _parse_dt(s: Optional[str]):
    """解析 ISO 时间戳(兼容尾部 Z 与带偏移量)为 UTC aware datetime, 失败返回 None。"""
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _is_trusted_today_usage_report(
    *,
    usage_source: Optional[str],
    usage_window_start: Optional[str],
    server_timestamp: Optional[str],
) -> bool:
    """只信任明确声明且能验证为“本地当天零点至今”的用量上报。"""
    if str(usage_source or "").strip() != _TRUSTED_USAGE_SOURCE:
        return False
    window_start = _parse_dt_preserve_timezone(usage_window_start)
    server_ts = _parse_dt_preserve_timezone(server_timestamp)
    if window_start is None or server_ts is None:
        return False
    expected_start = server_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    delta_seconds = abs(
        (
            window_start.astimezone(timezone.utc)
            - expected_start.astimezone(timezone.utc)
        ).total_seconds()
    )
    return delta_seconds <= _USAGE_WINDOW_TOLERANCE_SECONDS


def _is_plausible_today_usage(rec: dict) -> bool:
    """判断一条上报是否真是"当天 00:00 至今"的累计用量。

    不变量: 若应用最近一次前台使用(last_used_time)在今天 00:00 之前,
    则"今天"用量应为 ~0; 此时仍带有大量用量说明该值是 24h 滚动窗口/历史脏数据,
    应当丢弃, 否则后端会拿昨天的峰值去比今天的限额, 误触发"超限"。
    信息不足(缺字段)时信任原值, 不做拦截。
    """
    usage_ms = int(rec.get("usage_time_ms", 0) or 0)
    if usage_ms <= 0:
        return True
    last_used = _parse_dt(rec.get("last_used_time"))
    st = _parse_dt_preserve_timezone(rec.get("server_timestamp"))
    if last_used is None or st is None:
        return True
    # 以 server_timestamp 原始时区所在日期的当地 00:00 作为"今天起点"
    today_midnight_utc = st.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)
    # 最后使用在昨天, 但用量仍 >5 分钟 => 脏数据(用量全来自昨天)
    if last_used < today_midnight_utc and usage_ms > 5 * 60 * 1000:
        return False
    return True


# ==================== 数字健康: 应用使用时长读取 ====================


def read_today_app_usage(target_date: Optional[str] = None) -> List[dict]:
    """读取指定日期(默认今天)的应用使用时长上报记录。

    由于 DataSyncWorker 每 15 分钟上报一次, 同一天会有多条记录。
    这里按 package_name 聚合: 取每个应用 server_timestamp 最新的一条记录
    (UsageStatsManager 返回"当天 00:00 至今"的累计, 最新上报 = 最准确),
    不再取历史最大值, 避免某天峰值被"冻住"。

    Returns:
        聚合后的应用使用时长列表 (按 usage_time_ms 降序)
    """
    if target_date:
        try:
            y, m, d = target_date.split("-")
            daily_dir = (
                get_user_daily_dir() / y / m / d
            )
        except Exception:
            daily_dir = _ensure_daily_dir()
    else:
        daily_dir = _ensure_daily_dir()

    usage_file = daily_dir / "app_usage.jsonl"
    if not usage_file.exists():
        return []

    aggregated: Dict[str, dict] = {}
    try:
        records: List[dict] = []
        with open(usage_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                records.append(rec)

        # 旧 24h 口径在午夜后会留下“最后使用在昨天、用量却很大”的基线。
        # 当天稍后只更新 last_used_time 时，不能把仍包含该基线的记录重新放行。
        legacy_baseline_by_package: Dict[str, int] = {}
        for rec in records:
            pkg = rec.get("package_name")
            if not pkg or _is_plausible_today_usage(rec):
                continue
            legacy_baseline_by_package[pkg] = max(
                legacy_baseline_by_package.get(pkg, 0),
                int(rec.get("usage_time_ms", 0) or 0),
            )

        for rec in records:
            pkg = rec.get("package_name")
            if not pkg:
                continue
            trusted = _is_trusted_today_usage_report(
                usage_source=rec.get("usage_source"),
                usage_window_start=rec.get("usage_window_start"),
                server_timestamp=rec.get("server_timestamp"),
            )
            # 丢弃 24h 滚动窗口/历史脏数据: 最近一次前台使用在昨天却带着大量用量。
            if not _is_plausible_today_usage(rec):
                continue
            baseline = legacy_baseline_by_package.get(pkg, 0)
            usage_ms = int(rec.get("usage_time_ms", 0) or 0)
            if not trusted and baseline > 0 and usage_ms >= int(baseline * 0.8):
                continue
            # 取 server_timestamp 最新的一条 (代表该应用当天最后一次上报的累计);
            # 可信 today-window 数据始终优先于旧客户端记录。
            st = rec.get("server_timestamp", "")
            existing = aggregated.get(pkg)
            existing_trusted = bool((existing or {}).get("_trusted"))
            if existing is None or (trusted and not existing_trusted) or (
                trusted == existing_trusted and st > existing.get("server_timestamp", "")
            ):
                aggregated[pkg] = {
                    "package_name": pkg,
                    "app_name": rec.get("app_name", pkg),
                    "usage_time_ms": usage_ms,
                    "launch_count": int(rec.get("launch_count", 0) or 0),
                    "last_used_time": rec.get("last_used_time"),
                    "server_timestamp": st,
                    "_trusted": trusted,
                }
    except Exception as e:
        logger.warning(f"读取今日应用使用时长失败: {e}")
        return []

    cleaned = []
    for item in aggregated.values():
        item = dict(item)
        item.pop("_trusted", None)
        cleaned.append(item)
    return sorted(
        cleaned,
        key=lambda x: x["usage_time_ms"],
        reverse=True,
    )


# ==================== 数字健康: 应用使用时长限额 REST 接口 ====================
#
# 供 Android 端「数字健康」设置页直接读写限额, 无需经过 LLM 工具调用。
# 底层复用 DigitalWellbeingService (与 nightly 自动设定 / set_app_limit 工具同源),
# 因此 UI 设定的限额与 Aveline 自动设定的限额完全一致, 互相覆盖生效。


class AppLimitItem(BaseModel):
    package_name: str
    app_name: str = ""
    limit_ms: int
    source: str = "user"


class AppLimitSetRequest(BaseModel):
    package_name: str
    app_name: str = ""
    limit_ms: int
    target_date: Optional[str] = None


class AppLimitResponse(BaseModel):
    date: str
    limits: List[dict]


@router.get("/wellbeing/app-limits", summary="获取应用使用时长限额(及今日用量进度)")
async def get_app_limits(target_date: Optional[str] = None):
    """返回某天的应用限额列表, 并附带每个应用的今日实际用量进度。

    - target_date 不传时默认取"今天"(数字健康核心诉求是看到今日真实用量)。
    - 当天无限额但有今日用量时, 回退返回这些应用的"今日已用"条目 (limit_ms=0),
      避免今天还没设限额时页面一片空白。
    - 返回的 limits[i] 含 usage_today_ms / ratio / session_cap_ms 字段, 供前端画进度条。
    """
    try:
        from core.services.digital_wellbeing.service import get_wellbeing_service

        wb = get_wellbeing_service()
        today_str = get_current_time().strftime("%Y-%m-%d")
        if not target_date:
            target_date = today_str

        limits_data = wb.get_limits(target_date)
        limits = limits_data.get("limits", {})

        # 取今日实际用量, 用于进度条 (按最新 server_timestamp 聚合)
        today_usage = {u["package_name"]: u for u in read_today_app_usage(today_str)}

        result = []
        for pkg, cfg in limits.items():
            limit_ms = int(cfg.get("limit_ms", 0) or 0)
            if limit_ms <= 0:
                continue
            u = today_usage.get(pkg)
            usage_ms = int(u.get("usage_time_ms", 0) or 0) if u else 0
            result.append(
                {
                    "package_name": pkg,
                    "app_name": cfg.get("app_name") or (u.get("app_name") if u else pkg) or pkg,
                    "limit_ms": limit_ms,
                    "source": cfg.get("source", "user"),
                    "usage_today_ms": usage_ms,
                    "ratio": round(usage_ms / limit_ms, 2) if limit_ms else 0,
                    "session_cap_ms": int(cfg.get("session_cap_ms", 0) or 0),
                }
            )

        # 回退: 当天无限额时, 把有今日用量的应用也展示出来 (limit_ms=0 = 未设限额)
        if not limits:
            for pkg, u in today_usage.items():
                usage_ms = int(u.get("usage_time_ms", 0) or 0)
                if usage_ms <= 0:
                    continue
                result.append(
                    {
                        "package_name": pkg,
                        "app_name": u.get("app_name") or pkg,
                        "limit_ms": 0,
                        "source": "none",
                        "usage_today_ms": usage_ms,
                        "ratio": 0.0,
                        "session_cap_ms": 0,
                    }
                )

        result.sort(key=lambda x: x["ratio"], reverse=True)
        return {
            "status": "success",
            "date": target_date,
            "limits": result,
        }
    except Exception as e:
        logger.error(f"获取应用限额失败: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/wellbeing/app-limit", summary="设置单个应用的使用时长限额")
async def set_app_limit(req: AppLimitSetRequest):
    """设置/覆盖单个应用的使用时长限额。

    - limit_ms<=0 视为移除该限额。
    - target_date 不传时默认存"明天"(与 set_app_limit 工具、nightly 一致)。
    """
    try:
        from core.services.digital_wellbeing.service import get_wellbeing_service

        wb = get_wellbeing_service()
        pkg = (req.package_name or "").strip()
        if not pkg:
            return error_response(ErrorCode.INVALID_PARAM, message="package_name 不能为空")

        wb.set_single_limit(
            package_name=pkg,
            limit_ms=req.limit_ms,
            app_name=req.app_name or pkg,
            target_date=req.target_date,
            source="user",
        )
        return {
            "status": "success",
            "message": "限额已保存" if req.limit_ms > 0 else "限额已移除",
            "package_name": pkg,
        }
    except Exception as e:
        logger.error(f"设置应用限额失败: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.delete("/wellbeing/app-limit/{package_name}", summary="移除单个应用的使用时长限额")
async def delete_app_limit(package_name: str, target_date: Optional[str] = None):
    """移除单个应用的使用时长限额 (等价于 set limit_ms=0)。"""
    try:
        from core.services.digital_wellbeing.service import get_wellbeing_service

        wb = get_wellbeing_service()
        wb.set_single_limit(
            package_name=package_name,
            limit_ms=0,
            source="user",
            target_date=target_date,
        )
        return {
            "status": "success",
            "message": "限额已移除",
            "package_name": package_name,
        }
    except Exception as e:
        logger.error(f"移除应用限额失败: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))
