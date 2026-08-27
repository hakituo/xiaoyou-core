# -*- coding: utf-8 -*-
"""健康数据存储层：快照覆盖 + 事件流追加。

设计动机
--------
旧实现每次同步写一个 ``YYYY-MM-DD_HH-MM-SS.json``，手机端 1 分钟同步一次
就是一天 1440 个文件，且没有任何消费方。这里改成两层结构：

- ``companion_data/health_sync/latest.json``
  当前健康快照（每次同步覆盖）。回答"她现在怎么样"这类问题。

- ``companion_data/health_sync/events/YYYY-MM-DD.jsonl``
  事件流（只追加，永不覆盖）。回答"今天几点心率多少 / 几点喝了多少水"
  这类带时间线的问题。只在数据**发生有意义的变化**时才写一条，
  避免把 1440 次同步原样堆进去。

事件类型
--------
``heart_rate``      心率（异常值或显著波动时记录）
``water``           饮水（按增量记录，时间 + 毫升）
``meal``            进食（按摄入热量增量记录，时间 + 热量/三大营养素）
``steps``           步数里程碑（每满 1000 步记一次）
``sleep_start``     入睡
``wake_up``         起床（触发退出低打扰的关键事件）
``body``            体成分（体重/体脂变化）
``vital``           血压/血糖/体温/血氧变化
``health_alert``    睡眠呼吸暂停征兆 / 心律不齐
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

from core.utils.data_paths import get_companion_data_dir
from core.utils.logger import get_logger
from core.utils.time_utils import now_iso, today_str, get_current_time

logger = get_logger("HealthSyncStore")

# 并发写保护：手机端高频同步 + 工具查询可能并发
_LOCK = threading.Lock()

# ===== 事件生成阈值 =====
# 心率：波动超过该值即记录一条
HEART_RATE_DELTA_BPM = 12
# 心率异常区间（静息心率参考，超出即视为异常并强制记录）
HEART_RATE_LOW = 50
HEART_RATE_HIGH = 110
# 步数里程碑步长
STEPS_MILESTONE = 1000
# 体重变化阈值 kg
WEIGHT_DELTA_KG = 0.3
# 体脂率变化阈值（0-1 尺度）
BODY_FAT_DELTA = 0.005
# 血氧变化阈值（0-1 尺度）
SPO2_DELTA = 0.02
# 体温变化阈值 °C
TEMP_DELTA = 0.3
# 血糖变化阈值 mmol/L
GLUCOSE_DELTA = 0.5
# 血压变化阈值 mmHg
BP_DELTA = 8


@dataclass
class HealthSyncResult:
    """一次同步的处理结果。"""

    events: List[Dict[str, Any]] = field(default_factory=list)
    # 检测到起床时，携带本次起床事件；否则为 None
    wake_up: Optional[Dict[str, Any]] = None
    saved_path: str = ""


def _base_dir() -> Path:
    base = get_companion_data_dir() / "health_sync"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _events_dir() -> Path:
    d = _base_dir() / "events"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _body_history_path() -> Path:
    """体成分历史趋势文件(追加式, 永不覆盖)。"""
    return _base_dir() / "body_history.jsonl"


def _latest_path() -> Path:
    return _base_dir() / "latest.json"


def read_latest() -> Dict[str, Any]:
    """读取最新健康快照，不存在时返回空字典。"""
    path = _latest_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取 latest.json 失败: %s", e)
        return {}


def read_daily_nutrition(date: str) -> Dict[str, Any]:
    """读取某天的饮食/饮水明细(按日期持久化, 支持查昨天/前天)。

    Args:
        date: YYYY-MM-DD
    Returns:
        {"nutrition_entries": [...], "water_intake_entries": [...]}
    """
    path = _nutrition_dir() / f"{date}.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取 nutrition/%s.json 失败: %s", date, e)
        return {}


def read_events(date_str: Optional[str] = None, limit: int = 200,
                types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """读取某日事件流。

    Args:
        date_str: ``YYYY-MM-DD``，缺省为今天
        limit: 最多返回多少条（取最近的）
        types: 只返回这些事件类型，None 表示全部
    """
    date_str = date_str or today_str()
    path = _events_dir() / f"{date_str}.jsonl"
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if types and rec.get("type") not in types:
                    continue
                rows.append(rec)
    except Exception as e:
        logger.warning("读取事件流 %s 失败: %s", date_str, e)
        return []
    return rows[-limit:] if limit and limit > 0 else rows


def _append_events(events: List[Dict[str, Any]]) -> None:
    """把事件追加到当日 jsonl。"""
    if not events:
        return
    path = _events_dir() / f"{today_str()}.jsonl"
    try:
        with open(path, "a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("写入健康事件流失败: %s", e)


def append_manual_event(event_type: str, **fields: Any) -> Dict[str, Any]:
    """手工追加一条事件（供饮水/进食等主动上报接口复用）。"""
    ev = {"ts": now_iso(), "type": event_type}
    ev.update({k: v for k, v in fields.items() if v is not None})
    with _LOCK:
        _append_events([ev])
    return ev


def append_body_history(snapshot: Dict[str, Any]) -> None:
    """把体成分快照追加到 body_history.jsonl。

    每次 ingest_snapshot 检测到体成分变化时调用。
    追加式存储, 永不覆盖, 供 AI 查询体重/体脂的历史趋势。
    """
    record = {"ts": now_iso()}
    for key in (
        "weight_kg", "body_fat_percent", "skeletal_muscle_percent",
        "muscle_mass", "body_fat_mass", "fat_free_mass",
        "skeletal_muscle_mass", "total_body_water",
        "height_m", "bmi", "basal_metabolic_rate",
    ):
        val = snapshot.get(key)
        if val is not None:
            record[key] = val
    # 只在有实际体成分数据时才追加
    if len(record) <= 1:
        return
    try:
        with open(_body_history_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("写入体成分历史失败: %s", e)


def read_body_history(limit: int = 100) -> List[Dict[str, Any]]:
    """读取体成分历史趋势(最近的 limit 条)。"""
    path = _body_history_path()
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("读取体成分历史失败: %s", e)
        return []
    return rows[-limit:] if limit and limit > 0 else rows


def _sync_user_status_body_metrics(snapshot: Dict[str, Any]) -> None:
    """体成分变化时同步更新 user_status.json 的 body_metrics。

    人设 prompt(detailed_persona.py) 从 user_status.json 读体重,
    不同步会导致 prompt 里的体重过期(Samsung 已读到新值但 user_status 还是旧的)。
    """
    try:
        from core.services.workspace.status_manager import get_user_status_manager

        mgr = get_user_status_manager()
        payload = mgr._load_payload()
        body_metrics = payload.get("body_metrics")
        if not isinstance(body_metrics, dict):
            body_metrics = {}
        changed = False
        # weight_kg
        w = _num(snapshot.get("weight_kg"))
        if w is not None and w != _num(body_metrics.get("weight_kg")):
            body_metrics["weight_kg"] = w
            changed = True
        # 其他体成分字段(体脂/骨骼肌/身高等)
        for key in (
            "body_fat_percent", "skeletal_muscle_percent",
            "muscle_mass", "body_fat_mass", "fat_free_mass",
            "skeletal_muscle_mass", "total_body_water",
            "height_m", "bmi", "basal_metabolic_rate",
        ):
            val = snapshot.get(key)
            if val is not None and val != body_metrics.get(key):
                body_metrics[key] = val
                changed = True
        if changed:
            body_metrics["weight_updated_at"] = time.time()
            payload["body_metrics"] = body_metrics
            mgr._save_payload(payload)
            logger.info("user_status body_metrics 已同步: weight_kg=%s", body_metrics.get("weight_kg"))
    except Exception as e:
        logger.warning("同步 user_status body_metrics 失败: %s", e)


def _num(value: Any) -> Optional[float]:
    """安全转 float，None/非数字返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta_exceeds(new: Any, old: Any, threshold: float) -> bool:
    """新值存在，且相对旧值变化超过阈值（旧值缺失时视为首次记录）。"""
    n = _num(new)
    if n is None:
        return False
    o = _num(old)
    if o is None:
        return True
    return abs(n - o) >= threshold


def _build_events(new: Dict[str, Any], old: Dict[str, Any]) -> List[Dict[str, Any]]:
    """对比新旧快照，生成需要落盘的事件列表。"""
    ts = now_iso()
    events: List[Dict[str, Any]] = []

    def emit(event_type: str, **fields: Any) -> Dict[str, Any]:
        ev = {"ts": ts, "type": event_type}
        ev.update({k: v for k, v in fields.items() if v is not None})
        events.append(ev)
        return ev

    # ---- 心率：异常值强制记录，正常值只在显著波动时记录 ----
    hr = _num(new.get("heart_rate"))
    if hr is not None:
        prev_hr = _num(old.get("heart_rate"))
        abnormal = hr < HEART_RATE_LOW or hr > HEART_RATE_HIGH
        changed = prev_hr is None or abs(hr - prev_hr) >= HEART_RATE_DELTA_BPM
        if abnormal or changed:
            emit(
                "heart_rate",
                bpm=int(hr),
                abnormal=abnormal,
                level=("偏低" if hr < HEART_RATE_LOW else "偏高" if hr > HEART_RATE_HIGH else "正常"),
                measured_at=new.get("heart_rate_timestamp"),
            )

    # ---- 饮水：按增量记录（时间 + 这次喝了多少 + 今日累计）----
    water_new = _num(new.get("water_intake_ml"))
    if water_new is not None:
        water_old = _num(old.get("water_intake_ml")) or 0.0
        delta = water_new - water_old
        # 跨天累计会被重置为更小值，此时不记负增量
        if delta > 0:
            emit("water", delta_ml=round(delta, 1), total_ml=round(water_new, 1))

    # ---- 进食：按摄入热量增量记录，与饮水字段是否存在无关 ----
    kcal_new = _num(new.get("nutrition_calories"))
    if kcal_new is not None:
        kcal_old = _num(old.get("nutrition_calories")) or 0.0
        delta = kcal_new - kcal_old
        if delta > 0:
            def _d(key: str) -> Optional[float]:
                n = _num(new.get(key))
                if n is None:
                    return None
                o = _num(old.get(key)) or 0.0
                d = n - o
                return round(d, 1) if d > 0 else None

            # 本次同步新增的食物名(让 timeline 也能看到"吃了什么")
            new_foods: List[str] = []
            for e in (new.get("nutrition_entries") or []):
                if isinstance(e, dict) and e.get("title"):
                    new_foods.append(str(e["title"]))

            emit(
                "meal",
                delta_kcal=round(delta, 1),
                total_kcal=round(kcal_new, 1),
                protein_g=_d("nutrition_protein"),
                carbs_g=_d("nutrition_carbs"),
                fat_g=_d("nutrition_fat"),
                foods=new_foods or None,
            )

    # ---- 步数里程碑：每满 1000 步记一次，避免每分钟都写 ----
    steps_new = _num(new.get("steps_today")) or _num(new.get("steps"))
    if steps_new is not None:
        steps_old = _num(old.get("steps_today")) or _num(old.get("steps")) or 0.0
        if int(steps_new // STEPS_MILESTONE) > int(steps_old // STEPS_MILESTONE):
            emit(
                "steps",
                steps=int(steps_new),
                milestone=int(steps_new // STEPS_MILESTONE) * STEPS_MILESTONE,
                distance_km=_num(new.get("total_distance_km")),
                active_minutes=new.get("active_time_minutes"),
            )

    # ---- 睡眠：入睡 / 起床 ----
    sleep_start = new.get("sleep_start_time")
    if sleep_start and sleep_start != old.get("sleep_start_time"):
        emit("sleep_start", sleep_start=sleep_start)

    sleep_end = new.get("sleep_end_time")
    if sleep_end and sleep_end != old.get("sleep_end_time"):
        emit(
            "wake_up",
            sleep_start=new.get("sleep_start_time"),
            sleep_end=sleep_end,
            sleep_minutes=new.get("sleep_minutes"),
            sleep_score=new.get("sleep_score"),
            deep_minutes=new.get("sleep_stage_deep_minutes"),
            rem_minutes=new.get("sleep_stage_rem_minutes"),
        )

    # ---- 体成分：体重/体脂变化 ----
    if (_delta_exceeds(new.get("weight_kg"), old.get("weight_kg"), WEIGHT_DELTA_KG)
            or _delta_exceeds(new.get("body_fat_percent"), old.get("body_fat_percent"), BODY_FAT_DELTA)):
        emit(
            "body",
            weight_kg=_num(new.get("weight_kg")),
            body_fat_percent=_num(new.get("body_fat_percent")),
            skeletal_muscle_mass=_num(new.get("skeletal_muscle_mass")),
            muscle_mass=_num(new.get("muscle_mass")),
            measured_at=new.get("weight_timestamp"),
        )

    # ---- 其他生命体征变化 ----
    vital_checks = (
        ("oxygen_saturation", SPO2_DELTA),
        ("blood_oxygen", SPO2_DELTA),
        ("body_temperature", TEMP_DELTA),
        ("skin_temperature", TEMP_DELTA),
        ("blood_glucose", GLUCOSE_DELTA),
        ("blood_pressure_systolic", BP_DELTA),
        ("blood_pressure_diastolic", BP_DELTA),
    )
    changed_vitals = {
        key: _num(new.get(key))
        for key, thr in vital_checks
        if _delta_exceeds(new.get(key), old.get(key), thr)
    }
    if changed_vitals:
        emit("vital", **changed_vitals)

    # ---- 健康预警：只在状态发生变化时记录，避免重复刷屏 ----
    for key, label in (("sleep_apnea_sign", "睡眠呼吸暂停征兆"),
                       ("irregular_heart_rhythm", "心律不齐")):
        val = new.get(key)
        if val and val != old.get(key):
            emit("health_alert", alert=key, label=label, value=val)

    return events


def _merge_entries(old_list: Optional[List[Dict[str, Any]]],
                   new_list: Optional[List[Dict[str, Any]]],
                   keys: tuple) -> List[Dict[str, Any]]:
    """按主键合并饮食/饮水明细列表(覆盖写, 不去重无主键的脏数据)。

    高频通道通常只在上报聚合快照时带全量明细; 这里按主键去重合并,
    保证 latest.json 里的明细是累计完整的, 不会被"只带部分条目"的同步覆盖掉。
    """
    if not new_list:
        return old_list or []
    merged: Dict[tuple, Dict[str, Any]] = {}
    for e in (old_list or []):
        if isinstance(e, dict):
            pk = tuple(e.get(k) for k in keys)
            merged[pk] = e
    for e in new_list:
        if isinstance(e, dict):
            pk = tuple(e.get(k) for k in keys)
            merged[pk] = e
    return [v for v in merged.values()]


def _nutrition_dir() -> Path:
    p = get_companion_data_dir() / "health_sync" / "nutrition"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _entry_date(entry: Dict[str, Any]) -> Optional[str]:
    """从明细的 time 字段解析出 YYYY-MM-DD（本地时区）。

    明细的 time 是 UTC（如 "2026-08-08T03:21:05Z"）。用户感知的"今天"是本地
    时区，北京时间比 UTC 早 8 小时。若直接按 UTC 取日期，本地 8/8 08:00 吃的
    饭（UTC 8/7 24:00）会被错归到 8/7，AI 用本地 today_str() 查询时查不到。
    这里统一把 UTC 时间转本地时区后再取日期，和查询端对齐。
    """
    t = entry.get("time") or entry.get("date")
    if not t:
        return None
    t = str(t)
    # 带 Z / 时区偏移的 ISO 时间：按 UTC 解析后转本地
    if ("Z" in t) or ("T" in t and ("+" in t[11:] or "-" in t[11:])):
        try:
            naive = datetime.fromisoformat(t.replace("Z", "+00:00"))
            utc_dt = naive.astimezone(pytz.utc)
            local_dt = utc_dt.astimezone(get_current_time().tzinfo)
            return local_dt.strftime("%Y-%m-%d")
        except Exception:
            return t[:10]
    # 无时区信息的纯日期/时间串，按字面日期处理（兜底）
    return t[:10]


def _write_daily_nutrition(merged: Dict[str, Any]) -> None:
    """把饮食/饮水明细按日期拆开、累计写入 nutrition/<date>.json。

    这样无论跨天多少次同步覆盖 latest.json, 任意一天(昨天/前天)的食物名
    都能通过日期查回来, 回答"昨天吃了什么"这类问题。
    """
    buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for key in ("nutrition_entries", "water_intake_entries"):
        for e in (merged.get(key) or []):
            if not isinstance(e, dict):
                continue
            d = _entry_date(e)
            if not d:
                continue
            buckets.setdefault(d, {}).setdefault(key, []).append(e)
    for d, data in buckets.items():
        path = _nutrition_dir() / f"{d}.json"
        old: Dict[str, List[Dict[str, Any]]] = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
            except Exception:
                old = {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        for key in ("nutrition_entries", "water_intake_entries"):
            # 饮食: 同一餐多条食物共享同一 startTime, 主键必须加 title,
            # 否则按 time 去重会把"一餐里的多道菜"合并成只剩一条。
            # 水饮: 每条记录时间天然不同, 且无 title 字段, 保持 time 主键。
            nkey = ("time", "title") if key == "nutrition_entries" else ("time",)
            out[key] = _merge_entries(old.get(key), data.get(key), keys=nkey)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("写入 nutrition/%s.json 失败: %s", d, e)


def ingest_snapshot(payload: Dict[str, Any]) -> HealthSyncResult:
    """接收一次同步快照：合并写 latest.json，并生成事件流。

    Args:
        payload: 手机端上报的字段字典（值为 None 的字段视为"本次没读到"，
                 不覆盖 latest 里的已有值，因为高频通道只读心率等少数字段）

    Returns:
        HealthSyncResult，含本次产生的事件与起床事件（若有）
    """
    with _LOCK:
        old = read_latest()

        # 高频通道只上报部分字段，None 表示"这次没读"，不能把旧值抹掉
        incoming = {k: v for k, v in payload.items() if v is not None}
        merged: Dict[str, Any] = dict(old)
        merged.update(incoming)
        # 饮食/饮水明细按主键累计合并, 避免高频通道整列表覆盖丢掉旧条目
        # 注意: 三星健康同一餐的多条食物共享同一 startTime, 饮食主键必须
        # 用 (time, title), 否则按 time 去重会把"一餐里的多道菜"合并成只剩
        # 一条(UI 显示全部、后端只剩每餐一件的根因)。水饮每条 time 不同, 无 title, 保持 time。
        merged["nutrition_entries"] = _merge_entries(
            old.get("nutrition_entries"), incoming.get("nutrition_entries"),
            keys=("time", "title"),
        )
        merged["water_intake_entries"] = _merge_entries(
            old.get("water_intake_entries"), incoming.get("water_intake_entries"),
            keys=("time",),
        )
        merged["server_timestamp"] = now_iso()

        events = _build_events(incoming, old)
        _append_events(events)

        # 体成分变化时, 追加到 body_history.jsonl(独立趋势文件, 不混入事件流)
        if any(e.get("type") == "body" for e in events):
            append_body_history(merged)
            # 同步更新 user_status.json 的 body_metrics, 让人设 prompt 用到最新体重
            _sync_user_status_body_metrics(merged)

        path = _latest_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("写入 latest.json 失败: %s", e)

        # 按日期持久化饮食/饮水明细, 支持"看昨天吃了什么"
        try:
            _write_daily_nutrition(merged)
        except Exception as e:
            logger.error("按日期写饮食明细失败: %s", e)

        wake_up = next((e for e in events if e.get("type") == "wake_up"), None)
        rel = str(path.relative_to(get_companion_data_dir())).replace("\\", "/")
        return HealthSyncResult(events=events, wake_up=wake_up, saved_path=rel)
