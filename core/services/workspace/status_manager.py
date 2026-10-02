import json
import os
import time
from typing import List, Dict, Any, Optional
from core.utils.common import get_project_root
from core.utils.logger import get_logger
from core.utils.data_paths import get_user_status_dir
from memory.core.persistence import safe_json_dump

logger = get_logger("STATUS_MANAGER")


class UserStatusManager:
    """
    管理用户的持续性状态（如：生病、溃疡、考试周、心情低落期）。
    这些状态不同于瞬时的情绪，它们会持续一段时间，直到被明确移除或过期。
    """

    def __init__(self):
        self.file_path = str((get_user_status_dir() / "user_status.json").resolve())
        self.legacy_file_path = os.path.join(
            get_project_root(), "core", "character", "configs", "user_status.json"
        )
        self._ensure_file()

    def _normalize_payload(self, data: Any) -> Dict[str, Any]:
        if isinstance(data, list):
            return {"statuses": data, "body_metrics": {}}
        if isinstance(data, dict):
            statuses = data.get("statuses")
            body_metrics = data.get("body_metrics")
            return {
                "statuses": statuses if isinstance(statuses, list) else [],
                "body_metrics": body_metrics if isinstance(body_metrics, dict) else {},
            }
        return {"statuses": [], "body_metrics": {}}

    def _ensure_file(self):
        if os.path.exists(self.file_path):
            self._bootstrap_weight_from_persona()
            return
        if os.path.exists(self.legacy_file_path):
            legacy_payload = self._load_payload_from_path(self.legacy_file_path)
            self._bootstrap_weight_from_persona(legacy_payload)
            self._save_payload(legacy_payload)
            return
        # 文件不存在时只写一次，直接包含默认体重
        payload = {"statuses": [], "body_metrics": {"weight_kg": 46.0, "weight_updated_at": time.time()}}
        self._save_payload(payload)

    def _bootstrap_weight_from_persona(self, payload: Optional[Dict[str, Any]] = None):
        if payload is None:
            payload = self._load_payload()
        body_metrics = payload.get("body_metrics")
        if not isinstance(body_metrics, dict):
            body_metrics = {}
        if isinstance(body_metrics.get("weight_kg"), (int, float)):
            return
        body_metrics["weight_kg"] = 46.0
        body_metrics["weight_updated_at"] = time.time()
        payload["body_metrics"] = body_metrics
        self._save_payload(payload)

    def _load_payload_from_path(self, path: str) -> Dict[str, Any]:
        try:
            if not os.path.exists(path):
                return {"statuses": [], "body_metrics": {}}
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return self._normalize_payload(data)
        except Exception as e:
            logger.error(f"Failed to load user statuses from {path}: {e}")
            return {"statuses": [], "body_metrics": {}}

    def _load_payload(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.file_path):
                return self._load_payload_from_path(self.file_path)
            if os.path.exists(self.legacy_file_path):
                payload = self._load_payload_from_path(self.legacy_file_path)
                self._save_payload(payload)
                return payload
            return {"statuses": [], "body_metrics": {}}
        except Exception as e:
            logger.error(f"Failed to load user status payload: {e}")
            return {"statuses": [], "body_metrics": {}}

    def _load_statuses(self) -> List[Dict[str, Any]]:
        payload = self._load_payload()
        statuses = payload.get("statuses")
        if isinstance(statuses, list):
            return statuses
        return []

    def _save_payload(self, payload: Dict[str, Any]):
        normalized = self._normalize_payload(payload)
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            safe_json_dump(normalized, self.file_path, "utf-8")
        except Exception as e:
            logger.error(f"Failed to save user status payload: {e}")

    def _save_statuses(self, statuses: List[Dict[str, Any]]):
        payload = self._load_payload()
        payload["statuses"] = statuses if isinstance(statuses, list) else []
        self._save_payload(payload)

    def add_status(
        self, name: str, description: str, duration_days: Optional[int] = None
    ) -> str:
        """
        添加一个新状态。
        :param name: 状态名称（如 "口腔溃疡"）
        :param description: 详细描述（如 "痛感明显，不能吃辣"）
        :param duration_days: 预计持续天数（可选，用于自动过期）
        """
        statuses = self._load_statuses()

        # 检查是否已存在同名状态，如果存在则更新
        for s in statuses:
            if s["name"] == name:
                s["description"] = description
                s["updated_at"] = time.time()
                if duration_days:
                    s["expires_at"] = time.time() + (duration_days * 86400)
                else:
                    if "expires_at" in s:
                        del s["expires_at"]
                self._save_statuses(statuses)
                return f"已更新状态：{name}"

        new_status = {
            "name": name,
            "description": description,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        if duration_days:
            new_status["expires_at"] = time.time() + (duration_days * 86400)

        statuses.append(new_status)
        self._save_statuses(statuses)
        return f"已添加状态：{name}"

    def remove_status(self, name: str) -> str:
        """移除一个状态"""
        statuses = self._load_statuses()
        initial_len = len(statuses)
        new_statuses = [s for s in statuses if s["name"] != name]

        if len(new_statuses) < initial_len:
            self._save_statuses(new_statuses)
            return f"已移除状态：{name}"
        return f"未找到状态：{name}"

    def get_active_statuses(self) -> List[Dict[str, Any]]:
        """获取当前所有有效状态，并自动清理过期状态"""
        statuses = self._load_statuses()
        now = time.time()
        active = []
        has_changes = False

        for s in statuses:
            if "expires_at" in s and s["expires_at"] < now:
                has_changes = True
                continue
            active.append(s)

        if has_changes:
            self._save_statuses(active)

        return active

    def get_status_summary(self) -> str:
        """获取用于 Prompt 的状态摘要"""
        statuses = self.get_active_statuses()
        body_metrics = self.get_body_metrics()
        if not statuses and not body_metrics:
            return "当前无特殊状态。"

        lines = ["【当前用户状态 (User Status)】"]
        weight_kg = body_metrics.get("weight_kg")
        if isinstance(weight_kg, (int, float)):
            lines.append(f"- 体重: {float(weight_kg):.1f}kg")
        for s in statuses:
            line = f"- {s['name']}: {s['description']}"
            if "expires_at" in s:
                days_left = int((s["expires_at"] - time.time()) / 86400)
                if days_left > 0:
                    line += f" (预计还剩 {days_left} 天)"
            lines.append(line)

        return "\n".join(lines)

    def get_body_metrics(self) -> Dict[str, Any]:
        payload = self._load_payload()
        body_metrics = payload.get("body_metrics")
        if isinstance(body_metrics, dict):
            return dict(body_metrics)
        return {}

    def set_weight_kg(self, weight_kg: float) -> Dict[str, Any]:
        payload = self._load_payload()
        body_metrics = payload.get("body_metrics")
        if not isinstance(body_metrics, dict):
            body_metrics = {}
        body_metrics["weight_kg"] = float(weight_kg)
        body_metrics["weight_updated_at"] = time.time()
        payload["body_metrics"] = body_metrics
        self._save_payload(payload)
        return dict(body_metrics)

    def get_storage_path(self) -> str:
        return self.file_path


_instance = None


def get_user_status_manager():
    global _instance
    if _instance is None:
        _instance = UserStatusManager()
    return _instance
