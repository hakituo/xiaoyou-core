"""
主动关怀检查器 - 初始化与状态恢复

负责管理检查器的决策时间戳状态，包括：
- 从持久化存储恢复状态
- 设置/更新下次决策时间
- 按 persona 维护独立的决策时间
"""
import time
from typing import Any, Callable, Dict

from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_INIT_STATE", "active_care_schedule.log")


class CheckerInitState:
    """主动关怀检查器 - 初始化与状态恢复

    管理决策时间戳状态，支持全局和 per-persona 两种粒度。
    """

    def __init__(
        self,
        storage: Any,
        get_config_value: Callable[[str, Any], Any],
    ):
        self._storage = storage
        self._get_config_value = get_config_value

        # 全局决策时间戳
        self.next_decision_ts: float = 0.0
        self._next_llm_decision_ts: float = 0.0

        # per-persona 决策时间戳
        self._next_decision_ts_by_persona: Dict[str, float] = {}
        self._next_llm_decision_ts_by_persona: Dict[str, float] = {}

    # ==================== 初始化 ====================

    async def initialize(self):
        """从持久化存储恢复决策时间戳状态"""
        try:
            state_data = await self._storage.get_proactive_state()
            persisted_next_ts = float(state_data.get("next_llm_decision_ts", 0.0))
            persisted_source = str(
                state_data.get("next_llm_decision_source") or "unknown"
            ).strip()
            now = time.time()

            if persisted_next_ts > now:
                default_next_check = self._get_config_value("active_care_default_next_check_seconds", 300)
                max_restore_wait = max(default_next_check * 3, 120)
                wait_seconds = int(persisted_next_ts - now)
                if persisted_source != "user_snooze" and wait_seconds > max_restore_wait:
                    persisted_next_ts = now + default_next_check
                    logger.info(
                        "Active Care: Clamped restored next check from %ss to %ss (source=%s).",
                        wait_seconds,
                        int(default_next_check),
                        persisted_source or "unknown",
                    )
                self._next_llm_decision_ts = persisted_next_ts
                self.next_decision_ts = persisted_next_ts
                logger.info(f"Active Care: Restored next check time from storage: {int(persisted_next_ts - now)}s later")
            else:
                logger.info("Active Care: No valid future check time found in storage.")

            persisted_by_persona = state_data.get("next_decision_ts_by_persona")
            if isinstance(persisted_by_persona, dict):
                for key, ts_val in persisted_by_persona.items():
                    ts = float(ts_val)
                    if ts > now:
                        self._next_decision_ts_by_persona[str(key)] = ts
                        self._next_llm_decision_ts_by_persona[str(key)] = ts
                if self._next_decision_ts_by_persona:
                    logger.info(
                        "Active Care: Restored per-persona next decision ts: %s",
                        {k: int(v - now) for k, v in self._next_decision_ts_by_persona.items() if v > now},
                    )
                    earliest = self._get_earliest_next_decision_ts()
                    self.next_decision_ts = earliest
                    self._next_llm_decision_ts = earliest
        except Exception as e:
            logger.warning(f"Active Care: Failed to load persisted state: {e}")

    # ==================== 决策时间戳管理 ====================

    async def set_next_decision_ts(
        self,
        ts: float,
        source: str = "system",
        persona_filename: str = "",
    ):
        """设置下次决策时间戳并持久化

        Args:
            ts: 目标时间戳
            source: 来源标识（如 "system", "user_snooze", "no_active_client" 等）
            persona_filename: 人设文件名，非空时只更新该 persona 的时间戳
        """
        if persona_filename:
            scope = self._storage.resolve_scope_from_persona_filename(persona_filename)
            persona_key = scope if scope else "default"
            self._next_llm_decision_ts_by_persona[persona_key] = ts
            self._next_decision_ts_by_persona[persona_key] = ts
        else:
            self._next_llm_decision_ts = ts
            self.next_decision_ts = ts
            # 无 persona_filename 时，同步更新所有已存在的 per-persona 条目
            for key in list(self._next_decision_ts_by_persona.keys()):
                if ts > self._next_decision_ts_by_persona[key]:
                    self._next_decision_ts_by_persona[key] = ts
                    self._next_llm_decision_ts_by_persona[key] = ts
        earliest_ts = self._get_earliest_next_decision_ts()
        self.next_decision_ts = earliest_ts
        self._next_llm_decision_ts = earliest_ts
        try:
            persist_data = {
                "next_llm_decision_ts": earliest_ts,
                "next_llm_decision_source": str(source or "system"),
                "next_llm_decision_written_ts": time.time(),
            }
            if self._next_decision_ts_by_persona:
                persist_data["next_decision_ts_by_persona"] = {
                    k: v for k, v in self._next_decision_ts_by_persona.items()
                }
            await self._storage.save_proactive_state(persist_data)
        except Exception as e:
            logger.warning(f"Active Care: Failed to save next decision ts: {e}")

    def _get_earliest_next_decision_ts(self) -> float:
        """获取所有决策时间戳中最早的一个"""
        all_ts = []
        if self._next_llm_decision_ts > 0:
            all_ts.append(self._next_llm_decision_ts)
        for ts in self._next_decision_ts_by_persona.values():
            if ts > 0:
                all_ts.append(ts)
        return min(all_ts) if all_ts else 0.0

    def get_next_decision_ts_for_persona(self, persona_filename: str) -> float:
        """获取指定 persona 的下次决策时间戳

        未初始化的 persona 回退到全局决策时间，避免启动延迟被绕过
        """
        scope = self._storage.resolve_scope_from_persona_filename(persona_filename)
        persona_key = scope if scope else "default"
        return self._next_decision_ts_by_persona.get(persona_key, self._next_llm_decision_ts)

    def get_all_persona_keys(self) -> list:
        """获取所有已注册的 persona key 列表，用于跨 persona 协调"""
        return list(self._next_decision_ts_by_persona.keys())
