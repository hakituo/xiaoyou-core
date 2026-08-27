"""
跨 persona 主动关怀时段分工注册表

职责：
- 管理 companion_data/dual_role/proactive_assignment_today.json 共享文件
- 提供读写接口供 PeerChatScheduler（协商时写入）和 CheckerActionFlow（发送前 check）使用
- 日期变更时自动滚动（清空重写）
- asyncio.Lock 保护并发写

数据结构示例：
{
  "date": "2026-07-10",
  "negotiation_status": "completed",  # pending | completed | failed
  "negotiated_at": 1783660500,
  "assignments": [
    {"time_slot": "morning", "lead": "aveline", "reason": "Aveline 上午精神好"},
    {"time_slot": "afternoon", "lead": "ling", "reason": "Ling 下午有空"},
    {"time_slot": "evening", "lead": "aveline", "reason": "Aveline 晚上更适合陪主人"}
  ],
  "last_send_ts": {
    "morning": {"aveline": 0.0, "ling": 0.0},
    "afternoon": {"aveline": 0.0, "ling": 0.0},
    "evening": {"aveline": 0.0, "ling": 0.0}
  }
}

时段定义（3 时段方案）：
- morning:    6 <= hour < 12
- afternoon: 12 <= hour < 18
- evening:   18 <= hour < 24
- night:      0 <= hour < 6  （不参与分工，睡眠策略覆盖，返回 ""）
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.data_paths import get_proactive_assignment_path
from core.utils.time_utils import get_current_time
from core.utils.async_locks import LazyAsyncLock

logger = get_logger("PROACTIVE_REGISTRY")

# 时段名称常量
SLOT_MORNING = "morning"
SLOT_AFTERNOON = "afternoon"
SLOT_EVENING = "evening"
SLOT_NIGHT = "night"  # 不参与分工

# 所有参与分工的时段
_ACTIVE_SLOTS = (SLOT_MORNING, SLOT_AFTERNOON, SLOT_EVENING)


def get_time_slot_from_hour(hour: int) -> str:
    """根据小时数返回时段名

    Args:
        hour: 0-23 的小时数

    Returns:
        "morning" / "afternoon" / "evening" / "night"
        night 时段（0-6）不参与分工，由睡眠策略覆盖。
    """
    if 6 <= hour < 12:
        return SLOT_MORNING
    if 12 <= hour < 18:
        return SLOT_AFTERNOON
    if 18 <= hour < 24:
        return SLOT_EVENING
    return SLOT_NIGHT


class ProactiveAssignmentRegistry:
    """跨 persona 主动关怀时段分工共享池读写器

    所有方法都是 async 的（文件 IO），线程安全用 asyncio.Lock 保护。
    """

    def __init__(self):
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_loaded_at: float = 0.0
        self._cache_ttl: float = 5.0  # 5 秒缓存，避免频繁读盘

    # ==================== 文件读写 ====================

    def _get_file_path(self) -> Path:
        return get_proactive_assignment_path()

    async def _read_raw(self) -> Dict[str, Any]:
        path = self._get_file_path()
        if not path.exists():
            return self._empty_structure()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return self._empty_structure()
            return data
        except Exception as e:
            logger.warning("ProactiveAssignmentRegistry: 读取共享文件失败: %s", e)
            return self._empty_structure()

    async def _write_raw(self, data: Dict[str, Any]) -> None:
        path = self._get_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def _empty_structure(self) -> Dict[str, Any]:
        """返回空结构"""
        return {
            "date": get_current_time().strftime("%Y-%m-%d"),
            "negotiation_status": "pending",
            "negotiated_at": 0.0,
            "assignments": [],
            "last_send_ts": {
                SLOT_MORNING: {"aveline": 0.0, "ling": 0.0},
                SLOT_AFTERNOON: {"aveline": 0.0, "ling": 0.0},
                SLOT_EVENING: {"aveline": 0.0, "ling": 0.0},
            },
        }

    def _is_expired(self, data: Dict[str, Any]) -> bool:
        today = get_current_time().strftime("%Y-%m-%d")
        return str(data.get("date", "")) != today

    async def _load(self, force_refresh: bool = False) -> Dict[str, Any]:
        now = time.time()
        if (
            not force_refresh
            and self._cache is not None
            and (now - self._cache_loaded_at) < self._cache_ttl
        ):
            return self._cache

        async with self._lock:
            data = await self._read_raw()
            if self._is_expired(data):
                logger.info(
                    "ProactiveAssignmentRegistry: 日期变更，重置共享池 (旧 date=%s)",
                    data.get("date"),
                )
                data = self._empty_structure()
                await self._write_raw(data)
            self._cache = data
            self._cache_loaded_at = now
            return data

    async def _save(self, data: Dict[str, Any]) -> None:
        async with self._lock:
            await self._write_raw(data)
            self._cache = data
            self._cache_loaded_at = time.time()

    # ==================== 对外接口：协商状态 ====================

    async def needs_negotiation(self) -> bool:
        """是否需要协商（仅 pending 状态返回 True）"""
        data = await self._load()
        status = str(data.get("negotiation_status", "pending"))
        return status == "pending"

    async def mark_negotiation_status(self, status: str, reason: str = "") -> None:
        """标记协商状态

        Args:
            status: "pending" | "completed" | "failed"
            reason: 失败原因（仅 failed 时有意义）
        """
        if status not in ("pending", "completed", "failed"):
            logger.warning("ProactiveAssignmentRegistry: 非法 status=%s", status)
            return
        data = await self._load(force_refresh=True)
        data["negotiation_status"] = status
        data["negotiated_at"] = time.time()
        if status == "failed" and reason:
            data["failure_reason"] = reason
        await self._save(data)
        logger.info(
            "ProactiveAssignmentRegistry: 协商状态标记为 %s%s",
            status, f" (reason={reason})" if reason else "",
        )

    async def set_assignments(self, assignments: List[Dict[str, Any]]) -> None:
        """写入分工结果（协商完成后调用）

        Args:
            assignments: [{"time_slot": "morning", "lead": "aveline", "reason": "..."}, ...]
        """
        data = await self._load(force_refresh=True)
        # 规范化并过滤无效项
        normalized = []
        for a in assignments or []:
            if not isinstance(a, dict):
                continue
            slot = str(a.get("time_slot") or "").strip().lower()
            lead = str(a.get("lead") or a.get("assigned_to") or "").strip().lower()
            reason = str(a.get("reason") or "").strip()
            if slot not in _ACTIVE_SLOTS:
                logger.warning(
                    "ProactiveAssignmentRegistry: 未知 time_slot=%s，跳过", slot
                )
                continue
            # 规范化 persona 名
            if lead in ("七濑 澪", "七濑澪", "澪", "aveline"):
                lead = "aveline"
            elif lead in ("Ling", "ling", "wang_ling"):
                lead = "ling"
            else:
                logger.warning(
                    "ProactiveAssignmentRegistry: 未知 lead=%s，跳过", lead
                )
                continue
            normalized.append({
                "time_slot": slot,
                "lead": lead,
                "reason": reason,
            })

        data["assignments"] = normalized
        data["negotiation_status"] = "completed"
        data["negotiated_at"] = time.time()
        await self._save(data)
        logger.info(
            "ProactiveAssignmentRegistry: 写入 %d 条时段分工: %s",
            len(normalized),
            [(a["time_slot"], a["lead"]) for a in normalized],
        )

    # ==================== 对外接口：发送前检查 ====================

    async def get_lead_for_slot(self, time_slot: str) -> str:
        """获取某时段的主导角色

        Args:
            time_slot: "morning" / "afternoon" / "evening"

        Returns:
            "aveline" / "ling" / ""（未分工或 night 时段返回空）
        """
        if time_slot not in _ACTIVE_SLOTS:
            return ""
        data = await self._load()
        for a in data.get("assignments", []):
            if str(a.get("time_slot", "")) == time_slot:
                return str(a.get("lead", ""))
        return ""

    async def get_current_lead(self) -> str:
        """获取当前时段的主导角色

        Returns:
            "aveline" / "ling" / ""（night 时段或未分工返回空）
        """
        now_hour = get_current_time().hour
        slot = get_time_slot_from_hour(now_hour)
        if slot == SLOT_NIGHT:
            return ""
        return await self.get_lead_for_slot(slot)

    async def get_effective_lead_for_slot(self, time_slot: str) -> str:
        """获取协商结果；协商缺失或失败时返回按日期稳定的兜底主导角色。"""
        lead = await self.get_lead_for_slot(time_slot)
        if lead or time_slot not in _ACTIVE_SLOTS:
            return lead

        # 同一天同一时段始终只允许一个角色，避免未协商时两边同时主动联系。
        slot_index = _ACTIVE_SLOTS.index(time_slot)
        day_index = get_current_time().date().toordinal()
        return ("aveline", "ling")[(day_index + slot_index) % 2]

    async def get_current_slot(self) -> str:
        """获取当前时段名"""
        now_hour = get_current_time().hour
        return get_time_slot_from_hour(now_hour)

    async def is_current_persona_lead(self, current_persona: str) -> bool:
        """判断当前角色是否是当前时段的主导

        Args:
            current_persona: "aveline" / "ling"

        Returns:
            True 表示当前角色主导当前时段。
            night 时段或未分工时返回 True（允许发，走睡眠策略兜底）。
        """
        slot = get_time_slot_from_hour(get_current_time().hour)
        lead = await self.get_effective_lead_for_slot(slot)
        if not lead:
            # 未分工或 night 时段，允许发（走兜底/睡眠策略）
            return True
        return lead == current_persona

    async def record_send(self, persona: str, time_slot: str = "") -> None:
        """记录某角色在某时段发送了主动关怀

        Args:
            persona: "aveline" / "ling"
            time_slot: 指定时段，为空时自动取当前时段
        """
        if not time_slot:
            now_hour = get_current_time().hour
            time_slot = get_time_slot_from_hour(now_hour)
        if time_slot not in _ACTIVE_SLOTS:
            return
        if persona not in ("aveline", "ling"):
            return

        data = await self._load(force_refresh=True)
        last_send = data.get("last_send_ts")
        if not isinstance(last_send, dict):
            last_send = {}
        slot_data = last_send.get(time_slot)
        if not isinstance(slot_data, dict):
            slot_data = {"aveline": 0.0, "ling": 0.0}
        slot_data[persona] = time.time()
        last_send[time_slot] = slot_data
        data["last_send_ts"] = last_send
        await self._save(data)

    async def can_take_over(
        self,
        current_persona: str,
        time_slot: str = "",
        timeout_seconds: float = 5400.0,
    ) -> bool:
        """判断次要角色是否可以接管（主导超时未发）

        兜底机制：主导角色超过 timeout_seconds 没在该时段发主动关怀，
        次要角色可以接管，避免用户长时间收不到消息。

        Args:
            current_persona: 当前角色
            time_slot: 指定时段，为空时取当前时段
            timeout_seconds: 主导超时阈值，默认 1.5 小时

        Returns:
            True 表示当前角色可以接管（主导超时未发）。
            night 时段或未分工时返回 True。
        """
        if not time_slot:
            now_hour = get_current_time().hour
            time_slot = get_time_slot_from_hour(now_hour)
        if time_slot not in _ACTIVE_SLOTS:
            return True  # night 时段，允许发

        lead = await self.get_effective_lead_for_slot(time_slot)
        if not lead:
            return True

        # 当前角色是主导，直接允许
        if lead == current_persona:
            return True

        # 当前角色是次要，检查主导是否超时未发
        data = await self._load()
        last_send = data.get("last_send_ts", {})
        slot_data = last_send.get(time_slot, {})
        lead_last_ts = float(slot_data.get(lead, 0.0))
        if lead_last_ts <= 0:
            # 主导今天在该时段从未发过，检查协商完成时间
            # 协商缺失时仍从当前时段起点算超时，不能让两个角色
            # 因“未协商”同时获得发送权。
            negotiated_at = float(data.get("negotiated_at", 0.0))
            if negotiated_at <= 0:
                slot_start_hour = {
                    SLOT_MORNING: 6,
                    SLOT_AFTERNOON: 12,
                    SLOT_EVENING: 18,
                }[time_slot]
                slot_started_at = get_current_time().replace(
                    hour=slot_start_hour,
                    minute=0,
                    second=0,
                    microsecond=0,
                ).timestamp()
                return (time.time() - slot_started_at) >= timeout_seconds
            elapsed = time.time() - negotiated_at
            return elapsed >= timeout_seconds
        # 主导发过，从最后一次发送算超时
        elapsed = time.time() - lead_last_ts
        return elapsed >= timeout_seconds

    async def get_other_persona_send_count_today(
        self, current_persona: str
    ) -> int:
        """获取对方今日在各时段的发送次数总和（用于轮流制兜底）

        Args:
            current_persona: 当前角色

        Returns:
            对方今日发送次数
        """
        data = await self._load()
        other = "ling" if current_persona == "aveline" else "aveline"
        last_send = data.get("last_send_ts", {})
        count = 0
        for slot in _ACTIVE_SLOTS:
            slot_data = last_send.get(slot, {})
            if float(slot_data.get(other, 0.0)) > 0:
                count += 1
        return count

    async def get_snapshot(self) -> Dict[str, Any]:
        """获取完整快照（供 API/调试用）"""
        return await self._load(force_refresh=True)


# ==================== 全局单例 ====================

_registry: Optional[ProactiveAssignmentRegistry] = None


def get_proactive_assignment_registry() -> ProactiveAssignmentRegistry:
    """获取 ProactiveAssignmentRegistry 单例"""
    global _registry
    if _registry is None:
        _registry = ProactiveAssignmentRegistry()
    return _registry
