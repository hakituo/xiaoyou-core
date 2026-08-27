import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Iterator
from core.utils.logger import get_logger
from core.utils.singleton import SingletonFactory
from core.utils.data_paths import get_user_daily_records_dir
from core.utils.time_utils import get_current_time, now_str, today_str

try:
    from filelock import FileLock, Timeout as FileLockTimeout
except ImportError:  # pragma: no cover - filelock 是项目依赖
    FileLock = None  # type: ignore[misc,assignment]
    FileLockTimeout = Exception  # type: ignore[misc,assignment]

logger = get_logger("DAILY_MANAGER")


class DailyActivityManager:
    """
    管理用户每日的生活画像（User Portrait）。
    数据存储在 companion_data/user_data/daily_records/YYYY/M/D/daily_record.json
    """

    # 起床时间可能同时来自聊天推断、用户明说和健康设备。
    # 数值越大越可靠，低优先级来源不得覆盖高优先级数据。
    WAKEUP_SOURCE_PRIORITIES = {
        "legacy": 0,
        "chat_inferred": 10,
        "chat_explicit_time": 30,
        "active_care_session": 40,
        "samsung_health": 80,
        "user_manual": 100,
    }

    def __init__(self):
        self.root_dir = str(get_user_daily_records_dir())
        os.makedirs(self.root_dir, exist_ok=True)

    def _normalize_date(self, date_str: Optional[str] = None) -> str:
        """解析日期字符串；未提供时默认"自然日今天"。

        注意：daily_record 是实时事件流水（饮食/学习/健康等），必须按自然日归属，
        不能用 get_diary_target_date_str()（其凌晨归属会覆盖到昨天——那是日记的
        归属语义）。睡眠/起床记录的跨天归属由 _resolve_sleep_record_date 单独处理。
        """
        raw = (date_str or "").strip()
        if not raw:
            return today_str()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except Exception:
            return today_str()

    def _get_legacy_file_path(self, date_str: str) -> str:
        return os.path.join(self.root_dir, f"{date_str}.json")

    def _get_previous_month_path(self, date_str: str) -> str:
        return os.path.join(
            self.root_dir, date_str[:4], date_str[5:7], f"{date_str}.json"
        )

    def _get_file_path(self, date_str: Optional[str] = None) -> str:
        normalized = self._normalize_date(date_str)
        year, month, day = normalized.split("-")
        day_dir = os.path.join(
            self.root_dir, str(int(year)), str(int(month)), str(int(day))
        )
        os.makedirs(day_dir, exist_ok=True)
        return os.path.join(day_dir, "daily_record.json")

    def _get_lock_path(self, date_str: str) -> str:
        """获取指定日期记录文件对应的跨平台文件锁路径。

        锁文件与 daily_record.json 同目录，名为 daily_record.lock。
        使用 filelock 库实现 Windows/Linux 通用互斥。
        """
        record_path = self._get_file_path(date_str)
        return record_path + ".lock"

    @contextmanager
    def _with_record_lock(
        self, date_str: Optional[str] = None, timeout: float = 10.0
    ) -> Iterator[None]:
        """对指定日期的记录加文件锁，保护 read-modify-write 操作的原子性。

        跨进程互斥：即使有多个 Python 进程同时写同一天的记录，
        也会通过 .lock 文件串行化，避免读后写导致的数据覆盖。

        若 filelock 未安装，则退化为无锁模式（仅记录 warning），不阻塞业务流程。
        """
        normalized = self._normalize_date(date_str)
        if FileLock is None:
            logger.warning(
                "filelock 未安装，daily record 写入无跨进程锁保护 (date=%s)",
                normalized,
            )
            yield
            return

        lock_path = self._get_lock_path(normalized)
        # 确保锁文件所在目录存在
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        lock = FileLock(lock_path, timeout=timeout)
        try:
            with lock:
                yield
        except FileLockTimeout:
            logger.error(
                "获取 daily record 文件锁超时 (date=%s, timeout=%ss)",
                normalized,
                timeout,
            )
            raise
        except Exception:
            raise

    def _get_previous_date(self, date_str: str) -> str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            dt = get_current_time()
        return (dt - timedelta(days=1)).strftime("%Y-%m-%d")

    def _resolve_sleep_record_date(
        self, time_str: Optional[str] = None, now_dt: Optional[datetime] = None
    ) -> str:
        current_dt = now_dt or get_current_time()
        target = current_dt.strftime("%Y-%m-%d")
        t_raw = str(time_str or "").strip()
        hour = current_dt.hour
        if t_raw:
            m = re.search(r"^([01]?\d|2[0-3])[:：]([0-5]?\d)$", t_raw)
            if m:
                hour = int(m.group(1))
        # 熬夜场景：凌晨0-9点的睡眠记录归到前一天
        # 这样用户凌晨1点、2点、...、8点睡觉都会记录为"昨晚"
        # 9点之后睡觉则认为是白天补觉或特殊作息，记录到当天
        if 0 <= hour < 9:
            return (current_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        return target

    def _default_record(self, normalized: str) -> Dict[str, Any]:
        return {
            "date": normalized,
            "sleep_cycle": {
                "sleep": None,
                "wakeup": None,
                "duration": None,
                "sleep_source": None,
                "sleep_recorded_at": None,
                "wakeup_source": None,
                "wakeup_recorded_at": None,
            },
            "meals": [],
            "study": {"sessions": [], "summary": ""},
            "activities": [],
            "summary": "",
        }

    def _normalize_record(self, data: Dict[str, Any], date_str: str) -> Dict[str, Any]:
        normalized = dict(data or {})
        normalized["date"] = self._normalize_date(normalized.get("date") or date_str)
        
        # 兼容旧格式 schedule -> 新格式 sleep_cycle
        if "schedule" in normalized and "sleep_cycle" not in normalized:
            schedule = normalized.pop("schedule")
            if isinstance(schedule, dict):
                normalized["sleep_cycle"] = {
                    "sleep": schedule.get("sleep"),
                    "wakeup": schedule.get("wakeup"),
                    "duration": None,
                    "sleep_source": None,
                    "sleep_recorded_at": None,
                    "wakeup_source": None,
                    "wakeup_recorded_at": None,
                }
            else:
                normalized["sleep_cycle"] = self._default_record(date_str)["sleep_cycle"]
        elif "sleep_cycle" not in normalized:
            normalized["sleep_cycle"] = self._default_record(date_str)["sleep_cycle"]
        else:
            sc = normalized["sleep_cycle"]
            if not isinstance(sc, dict):
                normalized["sleep_cycle"] = self._default_record(date_str)["sleep_cycle"]
            else:
                normalized["sleep_cycle"] = {
                    "sleep": sc.get("sleep"),
                    "wakeup": sc.get("wakeup"),
                    "duration": sc.get("duration"),
                    "sleep_source": sc.get("sleep_source"),
                    "sleep_recorded_at": sc.get("sleep_recorded_at"),
                    "wakeup_source": sc.get("wakeup_source"),
                    "wakeup_recorded_at": sc.get("wakeup_recorded_at"),
                }
        
        if not isinstance(normalized.get("meals"), list):
            normalized["meals"] = []
        study = normalized.get("study")
        if not isinstance(study, dict):
            study = {}
        sessions = study.get("sessions")
        if not isinstance(sessions, list):
            sessions = []
        normalized["study"] = {
            "sessions": sessions,
            "summary": study.get("summary", "")
        }
        if not isinstance(normalized.get("activities"), list):
            normalized["activities"] = []
        if "health" in normalized and not isinstance(normalized.get("health"), list):
            normalized["health"] = []
        if (
            "mood" in normalized
            and normalized.get("mood") is not None
            and not isinstance(normalized.get("mood"), (dict, str))
        ):
            normalized["mood"] = None
        if "summary" not in normalized:
            normalized["summary"] = ""
        return normalized

    def _compact_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        compacted = dict(data or {})
        if not compacted.get("health"):
            compacted.pop("health", None)
        if not compacted.get("mood"):
            compacted.pop("mood", None)
        if not str(compacted.get("summary") or "").strip():
            compacted.pop("summary", None)
        return compacted

    def _load_record(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        normalized = self._normalize_date(date_str)
        path = self._get_file_path(normalized)
        if not os.path.exists(path):
            previous_month_path = self._get_previous_month_path(normalized)
            if os.path.exists(previous_month_path):
                path = previous_month_path
        if not os.path.exists(path):
            legacy_path = self._get_legacy_file_path(normalized)
            if os.path.exists(legacy_path):
                path = legacy_path
        if not os.path.exists(path):
            return self._default_record(normalized)
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return self._normalize_record(raw, normalized)
        except Exception as e:
            logger.error(f"Failed to load daily record: {e}")
            return self._default_record(normalized)

    def get_record(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """获取指定日期的完整记录"""
        return self._load_record(date_str)

    def _save_record(self, data: Dict[str, Any], date_str: Optional[str] = None):
        path = self._get_file_path(date_str)
        try:
            normalized = self._normalize_record(data, self._normalize_date(date_str))
            compacted = self._compact_record(normalized)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(compacted, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save daily record: {e}")

    def _calc_sleep_duration(self, sleep_time: str, wakeup_time: str) -> Optional[str]:
        """计算睡眠时长，返回如 '11h23m' 格式

        合理性校验：sleep_cycle 记录的是夜间主睡眠，正常时长在 1h~16h 之间。
        超出此范围说明 sleep/wakeup 字段被误填（例如把聊天时间当成睡觉时间），
        此时返回 None 避免把错误时长（如 "31m" 或 "22h45m"）展示给 AI。
        """
        try:
            sh, sm = map(int, sleep_time.split(":"))
            wh, wm = map(int, wakeup_time.split(":"))
            sleep_min = sh * 60 + sm
            wakeup_min = wh * 60 + wm
            # 如果 wakeup < sleep，说明跨天了（凌晨睡，下午起）
            if wakeup_min < sleep_min:
                wakeup_min += 24 * 60
            diff = wakeup_min - sleep_min
            # 合理性校验：< 1h 或 > 16h 视为误填，不返回时长
            if diff <= 0 or diff < 60 or diff > 16 * 60:
                return None
            h = diff // 60
            m = diff % 60
            if h > 0 and m > 0:
                return f"{h}h{m}m"
            elif h > 0:
                return f"{h}h"
            else:
                return f"{m}m"
        except (ValueError, AttributeError):
            return None

    def _update_sleep_cycle_duration(self, data: Dict[str, Any]) -> None:
        """更新 sleep_cycle 的 duration 字段"""
        sc = data.get("sleep_cycle") or {}
        sleep_time = sc.get("sleep")
        wakeup_time = sc.get("wakeup")
        if sleep_time and wakeup_time:
            sc["duration"] = self._calc_sleep_duration(sleep_time, wakeup_time)
            data["sleep_cycle"] = sc

    def record_wakeup(
        self,
        time_str: Optional[str] = None,
        *,
        source: Optional[str] = None,
        target_date: Optional[str] = None,
        force: bool = False,
    ) -> str:
        """记录起床时间，并按来源可靠性防止错误覆盖。"""
        has_explicit_time = bool(time_str)
        if not time_str:
            time_str = now_str("%H:%M")
        record_date = self._normalize_date(target_date)
        default_source = "chat_explicit_time" if has_explicit_time else "chat_inferred"
        normalized_source = str(source or default_source).strip() or default_source
        incoming_priority = self.WAKEUP_SOURCE_PRIORITIES.get(normalized_source, 0)
        with self._with_record_lock(record_date):
            data = self._load_record(record_date)
            sc = data["sleep_cycle"]
            existing_wakeup = sc.get("wakeup")
            existing_source = str(sc.get("wakeup_source") or "legacy")
            existing_priority = self.WAKEUP_SOURCE_PRIORITIES.get(existing_source, 0)

            if existing_wakeup and not force:
                if existing_priority > incoming_priority:
                    logger.info(
                        "保留更可靠的起床时间: existing=%s(%s), ignored=%s(%s)",
                        existing_wakeup,
                        existing_source,
                        time_str,
                        normalized_source,
                    )
                    return f"Kept existing wakeup: {existing_wakeup} ({existing_source})"
                # 聊天推断不应因后续多轮对话持续向后漂移。
                if (
                    existing_priority == incoming_priority
                    and normalized_source in {"chat_inferred", "chat_explicit_time"}
                    and existing_wakeup != time_str
                ):
                    return f"Kept existing wakeup: {existing_wakeup} ({existing_source})"

            sc["wakeup"] = time_str
            sc["wakeup_source"] = normalized_source
            sc["wakeup_recorded_at"] = now_str("%Y-%m-%dT%H:%M:%S%z")
            data["sleep_cycle"] = sc
            self._update_sleep_cycle_duration(data)
            self._save_record(data, record_date)
        return f"Recorded wakeup: {time_str} ({normalized_source}, {record_date})"

    def record_sleep(
        self,
        time_str: Optional[str] = None,
        now_dt: Optional[datetime] = None,
        target_date: Optional[str] = None,
        *,
        source: Optional[str] = None,
        force: bool = False,
    ):
        """记录睡觉时间，并按来源可靠性防止聊天覆盖健康设备。
        
        Args:
            time_str: 时间字符串，如 "22:30"
            now_dt: 当前时间（用于测试）
            target_date: 指定日期，如 "2026-04-07"。如果不指定，则根据时间自动判断
        """
        if not time_str:
            time_str = (now_dt or get_current_time()).strftime("%H:%M")
        if target_date:
            record_date = target_date
        else:
            record_date = self._resolve_sleep_record_date(time_str, now_dt=now_dt)
        normalized_source = str(source or "chat_explicit_time").strip() or "chat_explicit_time"
        incoming_priority = self.WAKEUP_SOURCE_PRIORITIES.get(normalized_source, 0)
        with self._with_record_lock(record_date):
            data = self._load_record(record_date)
            sleep_cycle = data.get("sleep_cycle") or {}
            existing_sleep = sleep_cycle.get("sleep")
            existing_source = str(sleep_cycle.get("sleep_source") or "legacy")
            existing_priority = self.WAKEUP_SOURCE_PRIORITIES.get(existing_source, 0)
            if existing_sleep and not force and existing_priority > incoming_priority:
                return f"Kept existing sleep: {existing_sleep} ({existing_source})"
            if existing_sleep and not force and existing_sleep != time_str:
                try:
                    exist_h = int(existing_sleep.split(":")[0])
                    new_h = int(time_str.split(":")[0])
                    # 保护逻辑：已有的睡觉时间在晚上/凌晨（18-9点），新值在白天（5-10点）
                    # 这可能是误识别的起床时间覆盖了睡觉时间
                    is_existing_night_sleep = 18 <= exist_h <= 23 or 0 <= exist_h < 9
                    is_new_suspicious_daytime = 5 <= new_h < 10
                    if is_existing_night_sleep and is_new_suspicious_daytime:
                        return f"Kept existing sleep time: {existing_sleep} (ignored suspicious daytime value {time_str})"
                except (ValueError, IndexError):
                    pass
            data["sleep_cycle"]["sleep"] = time_str
            data["sleep_cycle"]["sleep_source"] = normalized_source
            data["sleep_cycle"]["sleep_recorded_at"] = now_str("%Y-%m-%dT%H:%M:%S%z")
            self._update_sleep_cycle_duration(data)
            self._save_record(data, record_date)
        return f"Recorded sleep: {time_str} ({normalized_source}, {record_date})"

    def update_sleep_cycle(
        self,
        sleep_time: Optional[str] = None,
        wakeup_time: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> str:
        """显式修改指定日期的 sleep_cycle 字段（绕过 record_sleep 的保护逻辑）

        用于用户明确指出记录错误时，由 AI 主动调用此方法修正数据。
        不会触发"夜间睡眠被白天时间覆盖"的保护逻辑，因为这是用户明确要求的修改。

        Args:
            sleep_time: 睡觉时间（HH:MM），None 表示不修改 sleep 字段
            wakeup_time: 起床时间（HH:MM），None 表示不修改 wakeup 字段
            target_date: 指定日期（YYYY-MM-DD），None 表示自动判断：
                         - 若提供 sleep_time 则按熬夜规则归到前一天/当天
                         - 否则默认今天
        """
        if not sleep_time and not wakeup_time:
            return "未提供修改字段，sleep/wakeup 至少需要一个"

        # 解析目标日期
        if target_date:
            record_date = self._normalize_date(target_date)
        elif sleep_time:
            record_date = self._resolve_sleep_record_date(sleep_time)
        else:
            record_date = self._normalize_date()

        changed = []
        with self._with_record_lock(record_date):
            data = self._load_record(record_date)
            sc = data.get("sleep_cycle") or {}
            if not isinstance(sc, dict):
                sc = {"sleep": None, "wakeup": None, "duration": None}
            if sleep_time:
                sc["sleep"] = sleep_time
                sc["sleep_source"] = "user_manual"
                sc["sleep_recorded_at"] = now_str("%Y-%m-%dT%H:%M:%S%z")
                changed.append(f"sleep={sleep_time}")
            if wakeup_time:
                sc["wakeup"] = wakeup_time
                sc["wakeup_source"] = "user_manual"
                sc["wakeup_recorded_at"] = now_str("%Y-%m-%dT%H:%M:%S%z")
                changed.append(f"wakeup={wakeup_time}")
            data["sleep_cycle"] = sc
            self._update_sleep_cycle_duration(data)
            self._save_record(data, record_date)

        change_str = ", ".join(changed) if changed else "无变更"
        return f"已修正作息记录 ({record_date}): {change_str}"

    def record_meal(self, meal_type: str, content: str):
        """记录饮食"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["meals"].append(
                {"type": meal_type, "content": content, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录饮食: {meal_type} - {content}"

    def upsert_meal(self, meal_type: str, content: str, time_str: Optional[str] = None):
        with self._with_record_lock():
            data = self._load_record()
            timestamp = str(time_str or now_str("%H:%M")).strip()
            meal_t = str(meal_type or "meal").strip() or "meal"
            payload = {
                "type": meal_t,
                "content": str(content or "").strip(),
                "time": timestamp
            }
            meals = data.get("meals")
            if not isinstance(meals, list):
                meals = []
                data["meals"] = meals
            replaced = False
            for idx in range(len(meals) - 1, -1, -1):
                item = meals[idx]
                if not isinstance(item, dict):
                    continue
                if str(item.get("type") or "").strip() == meal_t:
                    meals[idx] = payload
                    replaced = True
                    break
            if not replaced:
                meals.append(payload)
            self._save_record(data)
        return f"已校正饮食: {meal_t} - {payload['content']}"

    def record_drink(self, drink_type: str, content: str):
        """记录喝水"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["meals"].append(
                {"type": drink_type, "content": content, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录饮品: {content}"

    def record_study(self, topic: str, content: str):
        """记录学习"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["study"]["sessions"].append(
                {"topic": topic, "content": content, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录学习: {topic}"

    def record_activity(self, activity_type: str, content: str):
        """记录其他活动（游戏、娱乐、杂事）"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["activities"].append(
                {"type": activity_type, "content": content, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录活动: {content}"

    def record_health(self, symptom: str, detail: str = ""):
        """记录健康状态"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            if "health" not in data:
                data["health"] = []
            data["health"].append(
                {"symptom": symptom, "detail": detail, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录健康状态: {symptom}"

    def record_mood(self, mood: str, detail: str = ""):
        """记录心情"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["mood"] = {"mood": mood, "detail": detail, "time": timestamp}
            self._save_record(data)
        return f"已记录心情: {mood}"

    def _infer_schedule_pattern(self, days: int = 7) -> str:
        """从最近几天的记录推断作息规律（中位数+范围）"""
        today = self._normalize_date()
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        wakeups = []
        sleeps = []
        for i in range(1, days + 1):
            past_dt = today_dt - timedelta(days=i)
            past_str = past_dt.strftime("%Y-%m-%d")
            data = self._load_record(past_str)
            # 兼容新旧格式
            sc = data.get("sleep_cycle") or data.get("schedule") or {}
            w = sc.get("wakeup")
            s = sc.get("sleep")
            if w:
                wakeups.append((past_str, w))
            if s:
                sleeps.append((past_str, s))
        parts = []
        if wakeups:
            times = [t for _, t in wakeups]
            median = self._time_median(times)
            time_range = self._time_range(times)
            parts.append(f"Typical wakeup: {median}{time_range}")
        if sleeps:
            times = [t for _, t in sleeps]
            median = self._time_median(times)
            time_range = self._time_range(times)
            parts.append(f"Typical sleep: {median}{time_range}")
        if not parts:
            return ""
        return "【Recent Pattern】" + "; ".join(parts) + " (reference only)"

    @staticmethod
    def _time_to_minutes(time_str: str) -> int:
        """将 HH:MM 转换为从0点开始的分钟数，处理跨天（凌晨睡觉+24h）"""
        try:
            parts = time_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            return h * 60 + m
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def _minutes_to_time(minutes: int) -> str:
        """将分钟数转换回 HH:MM 格式"""
        minutes = minutes % (24 * 60)
        h = minutes // 60
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    def _time_median(self, times: list) -> str:
        """计算时间列表的中位数"""
        if not times:
            return ""
        minutes_list = [self._time_to_minutes(t) for t in times]
        # 对睡觉时间，如果跨越0点（如23:30, 00:30, 01:00），需要归一化
        # 简单处理：如果大部分值>12:00但有少量<6:00，将<6:00的+24h
        has_late = sum(1 for m in minutes_list if m > 12 * 60) > len(minutes_list) // 2
        if has_late:
            normalized = [m + 24 * 60 if m < 6 * 60 else m for m in minutes_list]
        else:
            normalized = minutes_list
        normalized.sort()
        n = len(normalized)
        mid = normalized[n // 2] if n % 2 == 1 else (normalized[n // 2 - 1] + normalized[n // 2]) // 2
        return self._minutes_to_time(mid)

    def _time_range(self, times: list) -> str:
        """计算时间列表的范围（最早-最晚）"""
        if len(times) < 2:
            return ""
        minutes_list = [self._time_to_minutes(t) for t in times]
        has_late = sum(1 for m in minutes_list if m > 12 * 60) > len(minutes_list) // 2
        if has_late:
            normalized = [m + 24 * 60 if m < 6 * 60 else m for m in minutes_list]
        else:
            normalized = minutes_list
        min_val = min(normalized)
        max_val = max(normalized)
        return f"（{self._minutes_to_time(min_val)}~{self._minutes_to_time(max_val)}）"

    def get_today_summary(self) -> str:
        """获取今日画像摘要，用于 System Prompt"""
        today = self._normalize_date()
        data = self._load_record(today)
        lines = ["【Today's Portrait】"]

        sc = data.get("sleep_cycle", {})
        wakeup = sc.get("wakeup")
        sleep = sc.get("sleep")
        duration = sc.get("duration")
        has_schedule = bool(wakeup or sleep)

        if sleep and wakeup:
            duration_str = f" ({duration})" if duration else ""
            lines.append(f"- Sleep: {sleep} → {wakeup}{duration_str}")
        elif wakeup:
            lines.append(f"- Wakeup: {wakeup}")
        elif sleep:
            lines.append(f"- Sleep: {sleep}")
        else:
            # Try to get sleep from previous day
            prev_date = self._get_previous_date(today)
            prev_data = self._load_record(prev_date)
            prev_sc = prev_data.get("sleep_cycle") or {}
            prev_sleep = prev_sc.get("sleep")
            if prev_sleep:
                lines.append(f"- Last night sleep: {prev_sleep}")

        if not has_schedule:
            pattern = self._infer_schedule_pattern()
            if pattern:
                lines.append(pattern)

        meals = data.get("meals", [])
        if meals:
            food_items = []
            drink_total = 0
            for m in meals:
                if m.get("type") == "drink":
                    match = re.search(r"(\d+)", str(m.get("content") or ""))
                    if match:
                        drink_total += int(match.group(1))
                else:
                    food_items.append(f"{m['type']}({m['content']})")

            meal_str = ", ".join(food_items) if food_items else "No meals recorded"
            if drink_total > 0:
                meal_str += f"; Water: {drink_total}ml"

            lines.append(f"- Meals: {meal_str}")
        else:
            lines.append("- Meals: No records (needs attention)")

        study = data.get("study", {}).get("sessions", [])
        if study:
            topics = set([s["topic"] for s in study])
            lines.append(f"- Study: {', '.join(topics)} ({len(study)} sessions)")

        acts = data.get("activities", [])
        if acts:
            act_strs = [f"{a['content']}" for a in acts]
            lines.append(f"- Activities: {', '.join(act_strs)}")

        health = data.get("health", [])
        if health:
            h_strs = [f"{h['symptom']}" for h in health]
            lines.append(f"- Health: {', '.join(h_strs)}")

        mood = data.get("mood")
        if mood:
            if isinstance(mood, dict):
                lines.append(f"- Mood: {mood.get('mood')} ({mood.get('detail', '')})")
            else:
                lines.append(f"- Mood: {mood}")

        return "\n".join(lines)


_daily_manager_factory = SingletonFactory(DailyActivityManager)


def get_daily_manager():
    return _daily_manager_factory.get()
