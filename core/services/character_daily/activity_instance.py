"""角色活动实例（ActivityInstance）。

DailyPlan 只回答“某个时间段做什么”；ActivityInstance 负责把这个槽位解析成
当天稳定的生活事实，例如“去商场买日用品、和同学一起、坐公共交通”。

实例按 role/date/slot 稳定生成并落盘。聊天、Active Care、Peer Chat 等消费者只读
同一份事实，避免每次问 LLM 都重新编故事。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from core.character.runtime_roles import is_autonomous_role
from core.services.character_daily.activity_model import ActivitySlot, DailyPlan
from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = (
    Path(get_project_root()) / "config" / "yaml" / "character_activity_instances.yaml"
)
_DEFAULT_STORE_DIR = (
    Path(get_project_root()) / "companion_data" / "character_daily"
)
_DEFAULT_STORE_FILE = "activity_instances.json"
_STORE_VERSION = 1
_KEEP_DAYS = 14


@dataclass(frozen=True)
class ActivityInstance:
    """一个 DailyPlan 槽位在某一天的具体生活事实。"""

    instance_id: str
    role_id: str
    date: str
    slot_key: str
    activity: str
    planned_start: str
    planned_end: str
    purpose: str = ""
    companion_mode: str = ""
    companion_profile_ids: tuple[str, ...] = ()
    location: str = ""
    transport: str = ""
    detail: str = ""
    resolution_source: str = "deterministic_config"
    resolved_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["companion_profile_ids"] = list(self.companion_profile_ids)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActivityInstance":
        return cls(
            instance_id=str(data.get("instance_id") or ""),
            role_id=str(data.get("role_id") or ""),
            date=str(data.get("date") or ""),
            slot_key=str(data.get("slot_key") or ""),
            activity=str(data.get("activity") or "idle"),
            planned_start=str(data.get("planned_start") or ""),
            planned_end=str(data.get("planned_end") or ""),
            purpose=str(data.get("purpose") or ""),
            companion_mode=str(data.get("companion_mode") or ""),
            companion_profile_ids=tuple(
                str(item) for item in (data.get("companion_profile_ids") or []) if str(item)
            ),
            location=str(data.get("location") or ""),
            transport=str(data.get("transport") or ""),
            detail=str(data.get("detail") or ""),
            resolution_source=str(data.get("resolution_source") or "deterministic_config"),
            resolved_at=float(data.get("resolved_at") or 0.0),
        )

    def prompt_text(self) -> str:
        """生成可直接注入角色上下文的简短事实描述。"""
        parts = [f"当前安排：{self.activity}"]
        if self.purpose:
            parts.append(f"具体是{self.purpose}")
        if self.companion_mode:
            companion_labels = {
                "alone": "自己一个人",
                "friend": "和朋友一起",
                "classmate": "和同学一起",
                "classmates": "和同学一起",
                "labmates": "和实验室同学一起",
                "online_friends": "和熟人在线一起",
                "online_collaboration": "和别人线上协作",
            }
            parts.append(companion_labels.get(self.companion_mode, self.companion_mode))
        if self.location:
            parts.append(f"地点在{self.location}")
        if self.transport:
            parts.append(f"出行方式是{self.transport}")
        if self.detail:
            parts.append(self.detail)
        return "；".join(parts)


def _stable_fraction(*parts: object) -> float:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return value / float((1 << 64) - 1)


def _pick_weighted(options: Any, *seed_parts: object) -> str:
    if not isinstance(options, list) or not options:
        return ""
    parsed: list[tuple[str, float]] = []
    for option in options:
        if isinstance(option, str):
            value = option.strip()
            weight = 1.0
        elif isinstance(option, dict):
            value = str(option.get("value") or "").strip()
            try:
                weight = max(0.0, float(option.get("weight", 1.0)))
            except (TypeError, ValueError):
                weight = 1.0
        else:
            continue
        if value and weight > 0:
            parsed.append((value, weight))
    total = sum(weight for _, weight in parsed)
    if total <= 0:
        return ""
    cursor = _stable_fraction(*seed_parts) * total
    for value, weight in parsed:
        cursor -= weight
        if cursor <= 0:
            return value
    return parsed[-1][0]


def _load_instance_profiles() -> dict[str, Any]:
    try:
        if not _CONFIG_PATH.exists():
            return {}
        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        roles = raw.get("roles") if isinstance(raw, dict) else {}
        return roles if isinstance(roles, dict) else {}
    except Exception as exc:  # noqa: BLE001 - 细化失败不应阻断日常引擎
        logger.warning("加载 ActivityInstance 配置失败: %s", exc)
        return {}


class ActivityInstanceResolver:
    """把 ActivitySlot 解析成稳定的具体生活事实。"""

    def __init__(self, profiles: Optional[dict[str, Any]] = None):
        self._profiles = profiles if profiles is not None else _load_instance_profiles()

    def resolve(
        self,
        role_id: str,
        date_str: str,
        slot: ActivitySlot,
    ) -> ActivityInstance:
        role_id = str(role_id or "").strip().lower()
        slot_key = slot.slot_key()
        activity = slot.activity.value
        role_profile = self._profiles.get(role_id) or {}
        activity_profile = (
            role_profile.get(activity) if isinstance(role_profile, dict) else {}
        ) or {}
        seed = (role_id, date_str, slot_key, activity)

        purpose = _pick_weighted(activity_profile.get("purpose"), *seed, "purpose")
        companion_mode = _pick_weighted(
            activity_profile.get("companion_mode"), *seed, "companion"
        )
        location = _pick_weighted(activity_profile.get("location"), *seed, "location")
        transport = _pick_weighted(
            activity_profile.get("transport"), *seed, "transport"
        )
        detail = _pick_weighted(activity_profile.get("detail"), *seed, "detail")
        instance_id = hashlib.sha256(
            f"{role_id}|{date_str}|{slot_key}".encode("utf-8")
        ).hexdigest()[:20]
        return ActivityInstance(
            instance_id=instance_id,
            role_id=role_id,
            date=date_str,
            slot_key=slot_key,
            activity=activity,
            planned_start=slot.planned_start.isoformat(),
            planned_end=slot.planned_end.isoformat(),
            purpose=purpose,
            companion_mode=companion_mode,
            location=location,
            transport=transport,
            detail=detail,
            resolved_at=time.time(),
        )

    def resolve_plan(self, plan: DailyPlan) -> tuple[ActivityInstance, ...]:
        """细化一整天；非自主生活角色不会生成实例。"""
        if not is_autonomous_role(plan.role_id):
            return ()
        return tuple(
            self.resolve(plan.role_id, plan.date, slot)
            for slot in plan.slots
        )


class ActivityInstanceStore:
    """ActivityInstance 的 JSON 持久化存储。"""

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        filename: str = _DEFAULT_STORE_FILE,
    ):
        self._state_dir = state_dir or _DEFAULT_STORE_DIR
        self._state_file = self._state_dir / filename
        self._lock = threading.RLock()

    @property
    def state_file_path(self) -> Path:
        return self._state_file

    def _load_raw(self) -> dict[str, Any]:
        if not self._state_file.exists():
            return {"version": _STORE_VERSION, "dates": {}}
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("root is not object")
            if not isinstance(data.get("dates"), dict):
                data["dates"] = {}
            data["version"] = _STORE_VERSION
            return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取 ActivityInstance 状态失败，按空状态处理: %s", exc)
            return {"version": _STORE_VERSION, "dates": {}}

    def get(
        self,
        role_id: str,
        date_str: str,
        slot_key: str,
    ) -> Optional[ActivityInstance]:
        with self._lock:
            data = self._load_raw()
            raw = (
                data.get("dates", {})
                .get(date_str, {})
                .get(str(role_id or "").strip().lower(), {})
                .get(slot_key)
            )
            return ActivityInstance.from_dict(raw) if isinstance(raw, dict) else None

    def get_for_slot(
        self,
        plan: DailyPlan,
        slot: ActivitySlot,
        *,
        resolve_if_missing: bool = True,
        resolver: Optional[ActivityInstanceResolver] = None,
    ) -> Optional[ActivityInstance]:
        existing = self.get(plan.role_id, plan.date, slot.slot_key())
        if existing is not None or not resolve_if_missing:
            return existing
        if not is_autonomous_role(plan.role_id):
            return None
        resolved = (resolver or ActivityInstanceResolver()).resolve(
            plan.role_id, plan.date, slot
        )
        self.save_many((resolved,))
        return resolved

    def save_many(self, instances: Iterable[ActivityInstance]) -> int:
        items = tuple(instances)
        if not items:
            return 0
        with self._lock:
            data = self._load_raw()
            dates = data.setdefault("dates", {})
            written = 0
            for instance in items:
                role_bucket = dates.setdefault(instance.date, {}).setdefault(
                    instance.role_id, {}
                )
                # 已经解析过的事实不覆盖：nightly 重跑仍保持同一天事实稳定。
                if instance.slot_key in role_bucket:
                    continue
                role_bucket[instance.slot_key] = instance.to_dict()
                written += 1
            self._prune(dates)
            if written:
                self._state_dir.mkdir(parents=True, exist_ok=True)
                tmp_file = self._state_file.with_suffix(".tmp")
                tmp_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp_file.replace(self._state_file)
            return written

    @staticmethod
    def _prune(dates: dict[str, Any]) -> None:
        today = datetime.now().date()
        cutoff = today - timedelta(days=_KEEP_DAYS)
        for key in list(dates):
            try:
                parsed = datetime.strptime(key, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                dates.pop(key, None)
                continue
            if parsed < cutoff:
                dates.pop(key, None)


def get_current_activity_instance(
    plan: DailyPlan,
    now: datetime,
    *,
    store: Optional[ActivityInstanceStore] = None,
) -> Optional[ActivityInstance]:
    """读取当前槽位的稳定 ActivityInstance；缺失时按同一规则补建一次。"""
    slot = plan.find_current_slot(now)
    if slot is None:
        return None
    return (store or ActivityInstanceStore()).get_for_slot(plan, slot)
