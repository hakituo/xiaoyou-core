#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import threading
import time
from typing import Any, Dict, Optional

from core.utils.data_paths import get_user_data_dir


def _atomic_write_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    os.replace(tmp, path)


class UserPhysiologyService:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest_by_user: Dict[str, Dict[str, Any]] = {}

    def _runtime_dir(self) -> str:
        return str(get_user_data_dir())

    def _state_path(self) -> str:
        return os.path.join(self._runtime_dir(), "user_physiology.json")

    def _load_from_disk_locked(self) -> None:
        path = self._state_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                latest = obj.get("latest_by_user")
                if isinstance(latest, dict):
                    self._latest_by_user = latest
        except Exception:
            return

    def _persist_locked(self) -> None:
        data = {
            "updated_at": time.time(),
            "latest_by_user": self._latest_by_user,
        }
        try:
            _atomic_write_json(self._state_path(), data)
        except Exception:
            pass

    def _sanitize_metrics(self, metrics: Any) -> Dict[str, Any]:
        if not isinstance(metrics, dict):
            return {}

        out: Dict[str, Any] = {}

        def _put_float(
            name: str,
            v: Any,
            min_v: Optional[float] = None,
            max_v: Optional[float] = None,
        ) -> None:
            try:
                fv = float(v)
            except Exception:
                return
            if min_v is not None and fv < min_v:
                return
            if max_v is not None and fv > max_v:
                return
            out[name] = fv

        def _put_int(
            name: str, v: Any, min_v: Optional[int] = None, max_v: Optional[int] = None
        ) -> None:
            try:
                iv = int(v)
            except Exception:
                return
            if min_v is not None and iv < min_v:
                return
            if max_v is not None and iv > max_v:
                return
            out[name] = iv

        _put_float("heart_rate_bpm", metrics.get("heart_rate_bpm"), 20, 250)
        _put_float("spo2_percent", metrics.get("spo2_percent"), 50, 100)
        _put_float(
            "sleep_hours_last_night", metrics.get("sleep_hours_last_night"), 0, 24
        )
        _put_float("ambient_light_lux", metrics.get("ambient_light_lux"), 0, None)

        # Boolean metrics
        if "is_sleeping" in metrics:
            out["is_sleeping"] = bool(metrics["is_sleeping"])

        _put_int("steps_today", metrics.get("steps_today"), 0, 200000)

        _put_float("stress_level", metrics.get("stress_level"), 0.0, 1.0)
        _put_float("body_temperature_c", metrics.get("body_temperature_c"), 30.0, 45.0)

        # 应用使用统计 (新增)
        usage = metrics.get("usage_stats")
        if isinstance(usage, list):
            # 限制条数和长度
            out["usage_stats"] = [str(u)[:100] for u in usage[:10]]

        activity = metrics.get("activity")
        if isinstance(activity, str):
            a = activity.strip()
            if a:
                out["activity"] = a[:64]

        return out

    def _derive_flags(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        urgent: list[str] = []
        hr = metrics.get("heart_rate_bpm")
        spo2 = metrics.get("spo2_percent")
        sleep = metrics.get("sleep_hours_last_night")
        stress = metrics.get("stress_level")

        try:
            if hr is not None and float(hr) >= 110:
                urgent.append("high_heart_rate")
        except Exception:
            pass
        try:
            if spo2 is not None and float(spo2) <= 92:
                urgent.append("low_spo2")
        except Exception:
            pass
        try:
            if sleep is not None and float(sleep) <= 5.0:
                urgent.append("sleep_deprived")
        except Exception:
            pass
        try:
            if stress is not None and float(stress) >= 0.85:
                urgent.append("high_stress")
        except Exception:
            pass

        return {"urgent_needs": urgent}

    def update(self, user_id: str, payload: Any) -> Dict[str, Any]:
        uid = str(user_id or "default_user").strip() or "default_user"
        if not isinstance(payload, dict):
            payload = {}

        now = time.time()
        source = payload.get("source")
        if not isinstance(source, str) or not source.strip():
            source = "unknown"
        else:
            source = source.strip()[:32]

        measured_at = payload.get("measured_at")
        try:
            measured_at_ts = float(measured_at) if measured_at is not None else now
        except Exception:
            measured_at_ts = now

        metrics = self._sanitize_metrics(payload.get("metrics"))
        flags = self._derive_flags(metrics)

        record = {
            "user_id": uid,
            "updated_at": now,
            "measured_at": measured_at_ts,
            "source": source,
            "metrics": metrics,
            "flags": flags,
        }

        with self._lock:
            if not self._latest_by_user:
                self._load_from_disk_locked()
            self._latest_by_user[uid] = record
            self._persist_locked()
            return dict(record)

    def get_latest(
        self, user_id: str, stale_after_seconds: int = 20 * 60
    ) -> Optional[Dict[str, Any]]:
        uid = str(user_id or "default_user").strip() or "default_user"
        now = time.time()
        with self._lock:
            if not self._latest_by_user:
                self._load_from_disk_locked()
            rec = self._latest_by_user.get(uid)
            if not isinstance(rec, dict):
                return None
            updated_at = rec.get("updated_at")
            try:
                age = now - float(updated_at)
            except Exception:
                age = None
            out = dict(rec)
            out["age_seconds"] = age
            out["is_stale"] = bool(
                age is not None and age >= float(stale_after_seconds)
            )
            return out


_instance: Optional[UserPhysiologyService] = None
_instance_lock = threading.Lock()


def get_user_physiology_service() -> UserPhysiologyService:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = UserPhysiologyService()
        return _instance
