"""角色睡眠状态持久化。"""

from __future__ import annotations
from core.utils.logger import get_logger


import threading
from pathlib import Path
from typing import Dict

from core.services.life_simulation.sleep_models import SleepRuntimeState
from core.utils.atomic_io import safe_json_dump, safe_json_load

logger = get_logger(__name__)

_DEFAULT_STATE_DIR = Path(__file__).resolve().parents[3] / "companion_data" / "character_daily"
_DEFAULT_STATE_FILE = "sleep_states.json"


class SleepStateStore:
    """角色睡眠运行时状态存储。"""

    def __init__(self, state_dir: Path | None = None, filename: str = _DEFAULT_STATE_FILE):
        self._state_dir = state_dir or _DEFAULT_STATE_DIR
        self._state_file = self._state_dir / filename
        self._io_lock = threading.RLock()

    @property
    def state_file_path(self) -> Path:
        return self._state_file

    def load(self) -> Dict[str, SleepRuntimeState]:
        """加载所有角色睡眠状态。"""
        if not self._state_file.exists():
            return {}
        try:
            with self._io_lock:
                data = safe_json_load(self._state_file, default={})
            if not isinstance(data, dict):
                logger.warning("睡眠状态文件格式异常，已回退为空状态: %s", self._state_file)
                return {}
            result: Dict[str, SleepRuntimeState] = {}
            for role_id, item in dict(data or {}).items():
                if not isinstance(item, dict):
                    continue
                try:
                    result[str(role_id)] = SleepRuntimeState.from_dict(item)
                except Exception as exc:
                    logger.warning("加载角色睡眠状态失败: %s (%s)", role_id, exc)
            return result
        except Exception as exc:
            logger.error("读取睡眠状态文件失败: %s", exc)
            return {}

    def save(self, states: Dict[str, SleepRuntimeState]) -> None:
        """保存所有角色睡眠状态。"""
        try:
            payload = {role_id: state.to_dict() for role_id, state in states.items()}
            with self._io_lock:
                safe_json_dump(payload, self._state_file, use_fsync=True)
        except Exception as exc:
            logger.error("保存睡眠状态失败: %s", exc)
