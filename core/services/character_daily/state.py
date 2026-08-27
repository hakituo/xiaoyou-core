"""
角色日常状态持久化

负责 DailyState 的磁盘读写，确保重启后能恢复进度。
"""

from core.utils.logger import get_logger
import json

import time
from pathlib import Path

from core.services.character_daily.activity_model import DailyState

logger = get_logger(__name__)

# 默认持久化路径
_DEFAULT_STATE_DIR = Path(__file__).resolve().parents[3] / "companion_data" / "character_daily"
_DEFAULT_STATE_FILE = "daily_state.json"


class DailyStateStore:
    """角色日常状态持久化存储"""

    def __init__(self, state_dir: Path = None, filename: str = _DEFAULT_STATE_FILE):
        self._state_dir = state_dir or _DEFAULT_STATE_DIR
        self._state_file = self._state_dir / filename
        self._last_save_ts: float = 0.0
        self._min_save_gap: float = 10.0  # 最小保存间隔（秒）

    @property
    def state_file_path(self) -> Path:
        return self._state_file

    def load(self) -> DailyState:
        """从磁盘加载状态

        Returns:
            DailyState 实例，文件不存在或解析失败时返回空状态
        """
        if not self._state_file.exists():
            logger.info("CharacterDaily: 状态文件不存在，使用空状态: %s", self._state_file)
            return DailyState()

        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = DailyState.from_dict(data)
            logger.info(
                "CharacterDaily: 加载状态成功，date=%s, plans=%s",
                state.date,
                list(state.plans.keys()),
            )
            return state
        except Exception as e:
            logger.error("CharacterDaily: 加载状态失败: %s", e)
            return DailyState()

    def save(self, state: DailyState, immediate: bool = False) -> None:
        """将状态保存到磁盘

        Args:
            state: 要保存的状态
            immediate: 是否忽略节流立即保存（默认 False，有 10s 节流）
        """
        now = time.time()
        if not immediate and (now - self._last_save_ts) < self._min_save_gap:
            return  # 节流：太频繁的保存被跳过

        self._last_save_ts = now

        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = self._state_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
            # 原子替换
            tmp_file.replace(self._state_file)
            logger.debug("CharacterDaily: 状态已保存")
        except Exception as e:
            logger.error("CharacterDaily: 保存状态失败: %s", e)

    def clear(self) -> None:
        """清除磁盘上的状态文件"""
        try:
            if self._state_file.exists():
                self._state_file.unlink()
                logger.info("CharacterDaily: 状态文件已清除")
        except Exception as e:
            logger.error("CharacterDaily: 清除状态文件失败: %s", e)
