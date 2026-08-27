"""手动打断后的临时聊天窗口管理。

用于支持 QQ `/打断` 指令：角色本来在忙，但用户明确要求先聊天，
后续一小段时间内允许继续正常回复，不再被 busy defer 截断。

新增功能（2026-07-08）：
- 支持"跳过当前活动"：用户或 AI 可以决定跳过当前的学习任务，专心聊天
- 窗口延长：用户说"继续聊"时可以延长窗口

修复（2026-07-11）：
- /跳过 的窗口时长改为当前活动剩余时间（而非固定 300 秒），
  这样跳过整个活动期间都可以自由聊天，效果与 /打断 的临时窗口不同
- activate() 新增 skip_activity 参数，创建窗口时可直接标记跳过

修复（2026-08-03）：
- 窗口状态持久化到磁盘，backend 重启后 /跳过 / /打断 的窗口不再丢失
- activate/extend/mark_skip_activity/clear 时同步写盘
- 启动时加载未过期的窗口
"""

from __future__ import annotations
from core.utils.logger import get_logger


import threading
import time
from pathlib import Path
from typing import Any

logger = get_logger(__name__)


# 持久化文件路径：复用 character_daily 模块的数据目录约定
# 与 DailyStateStore 同目录（companion_data/character_daily/）
_PERSISTENCE_FILE = (
    Path(__file__).resolve().parents[3]
    / "companion_data"
    / "character_daily"
    / "interrupt_windows.json"
)


class InterruptWindowManager:
    """按会话维护手动打断后的聊天窗口。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, dict[str, Any]] = {}
        # 启动时从磁盘加载未过期的窗口
        self._load_from_disk()

    @staticmethod
    def _normalize_cid(conversation_id: str) -> str:
        """规范化 conversation_id，剥离 __persona__ 后缀。

        中断窗口按 base_user_id 查询，而不是按完整的 conversation_id（含 persona 后缀）。
        这样 persona 切换后（如从 qq/Ling_QQ_Master.json 切到 sensitive/Ling_love.json）
        仍能命中同一个窗口，避免中断窗口"消失"导致 persona_hint 不注入。

        例如：
        - private_10001__persona__ling_qq_master -> private_10001
        - private_10001__persona__ling_love -> private_10001
        - private_10001 -> private_10001（无后缀时不变）
        """
        cid = str(conversation_id or "").strip()
        if not cid:
            return cid
        if "__persona__" in cid:
            return cid.split("__persona__", 1)[0].strip("_")
        return cid

    def activate(
        self,
        *,
        conversation_id: str,
        role_id: str,
        activity: str,
        window_seconds: float,
        source: str = "manual_interrupt",
        skip_activity: bool = False,
    ) -> dict[str, Any]:
        now_ts = time.time()
        expire_ts = now_ts + max(1.0, float(window_seconds or 0.0))
        original_cid = str(conversation_id or "").strip()
        # 规范化 key：剥离 __persona__ 后缀，避免 persona 切换后窗口"消失"
        storage_key = self._normalize_cid(original_cid)
        payload = {
            "conversation_id": original_cid,
            "role_id": str(role_id or "").strip().lower(),
            "activity": str(activity or "").strip(),
            "window_seconds": float(window_seconds or 0.0),
            "source": str(source or "manual_interrupt").strip(),
            "started_ts": now_ts,
            "expire_ts": expire_ts,
            "skip_activity": bool(skip_activity),
            "extended_count": 0,  # 延长次数
        }
        if not original_cid:
            return {}
        snapshot: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._cleanup_locked(now_ts)
            self._windows[storage_key] = payload
            snapshot = self._snapshot_locked()
        self._save_to_disk_unlocked(snapshot)
        return dict(payload)

    def get_active(
        self,
        *,
        conversation_id: str,
        role_id: str = "",
    ) -> dict[str, Any] | None:
        original_cid = str(conversation_id or "").strip()
        if not original_cid:
            return None
        # 规范化 key：剥离 __persona__ 后缀，与 activate 时保持一致
        storage_key = self._normalize_cid(original_cid)
        role = str(role_id or "").strip().lower()
        now_ts = time.time()
        with self._lock:
            self._cleanup_locked(now_ts)
            payload = self._windows.get(storage_key)
            if not payload:
                return None
            payload_role = str(payload.get("role_id") or "").strip().lower()
            if role and payload_role and role != payload_role:
                return None
            return dict(payload)

    def extend(
        self,
        *,
        conversation_id: str,
        extend_seconds: float,
        max_extend_count: int = 3,
    ) -> dict[str, Any] | None:
        """延长窗口时间。

        Args:
            conversation_id: 会话 ID
            extend_seconds: 延长的秒数
            max_extend_count: 最大延长次数限制

        Returns:
            更新后的窗口信息，如果窗口不存在或已达上限则返回 None
        """
        original_cid = str(conversation_id or "").strip()
        if not original_cid or extend_seconds <= 0:
            return None
        storage_key = self._normalize_cid(original_cid)
        now_ts = time.time()
        snapshot: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._cleanup_locked(now_ts)
            payload = self._windows.get(storage_key)
            if not payload:
                return None
            extend_count = int(payload.get("extended_count") or 0)
            if extend_count >= max_extend_count:
                logger.info(
                    "InterruptWindow: 延长次数已达上限 %d，拒绝继续延长",
                    max_extend_count,
                )
                return None
            # 如果窗口已过期，则从当前时间开始计算
            current_expire = float(payload.get("expire_ts") or 0.0)
            new_expire = max(now_ts, current_expire) + extend_seconds
            payload["expire_ts"] = new_expire
            payload["extended_count"] = extend_count + 1
            logger.info(
                "InterruptWindow: 窗口延长 %.0fs，当前过期时间 %.0fs，延长次数 %d",
                extend_seconds,
                new_expire - now_ts,
                payload["extended_count"],
            )
            snapshot = self._snapshot_locked()
        self._save_to_disk_unlocked(snapshot)
        return dict(payload)

    def mark_skip_activity(
        self,
        *,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """标记跳过当前活动。

        Args:
            conversation_id: 会话 ID

        Returns:
            更新后的窗口信息，如果窗口不存在则返回 None
        """
        original_cid = str(conversation_id or "").strip()
        if not original_cid:
            return None
        storage_key = self._normalize_cid(original_cid)
        now_ts = time.time()
        snapshot: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._cleanup_locked(now_ts)
            payload = self._windows.get(storage_key)
            if not payload:
                return None
            payload["skip_activity"] = True
            logger.info(
                "InterruptWindow: 已标记跳过当前活动 %s",
                payload.get("activity"),
            )
            snapshot = self._snapshot_locked()
        self._save_to_disk_unlocked(snapshot)
        return dict(payload)

    def clear(self, conversation_id: str) -> None:
        original_cid = str(conversation_id or "").strip()
        if not original_cid:
            return
        storage_key = self._normalize_cid(original_cid)
        snapshot: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._windows.pop(storage_key, None)
            snapshot = self._snapshot_locked()
        self._save_to_disk_unlocked(snapshot)

    def _cleanup_locked(self, now_ts: float) -> None:
        expired = [
            cid
            for cid, payload in self._windows.items()
            if float(payload.get("expire_ts") or 0.0) <= now_ts
        ]
        for cid in expired:
            self._windows.pop(cid, None)

    # ===== 持久化 =====

    def _load_from_disk(self) -> None:
        """启动时从磁盘加载未过期的窗口。"""
        try:
            from core.utils.atomic_io import safe_json_load

            data = safe_json_load(_PERSISTENCE_FILE, default=None)
            if not isinstance(data, dict):
                return
            now_ts = time.time()
            loaded = 0
            with self._lock:
                for key, payload in data.items():
                    if not isinstance(payload, dict):
                        continue
                    expire_ts = float(payload.get("expire_ts") or 0.0)
                    if expire_ts > now_ts:
                        self._windows[key] = payload
                        loaded += 1
            if loaded:
                logger.info(
                    "InterruptWindow: 启动时从磁盘恢复 %d 个未过期窗口", loaded
                )
        except Exception as e:
            logger.warning("InterruptWindow: 加载持久化文件失败: %s", e)

    def _save_to_disk_unlocked(self, snapshot: dict[str, Any]) -> None:
        """将窗口快照写入磁盘（不加锁，调用方需在锁内取快照后释放锁再调用）。

        写盘放在锁外避免持锁 IO，调用方先用 _snapshot_locked 取快照。
        """
        try:
            from core.utils.atomic_io import safe_json_dump

            _PERSISTENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
            safe_json_dump(snapshot, _PERSISTENCE_FILE, use_fsync=True)
        except Exception as e:
            logger.warning("InterruptWindow: 保存持久化文件失败: %s", e)

    def _snapshot_locked(self) -> dict[str, dict[str, Any]]:
        """在锁内生成快照（深拷贝避免外部修改）。"""
        return {k: dict(v) for k, v in self._windows.items()}

    def get_expiring_windows(
        self,
        threshold_seconds: float = 60.0,
        now_ts: float | None = None,
    ) -> list[dict[str, Any]]:
        """获取即将过期的窗口列表（用于触发主动消息）。

        Args:
            threshold_seconds: 过期阈值（秒），窗口剩余时间 <= 此值时返回
            now_ts: 当前时间戳，None 则自动获取

        Returns:
            即将过期的窗口列表，每项包含窗口完整信息
        """
        if now_ts is None:
            now_ts = time.time()
        result = []
        with self._lock:
            self._cleanup_locked(now_ts)
            for cid, payload in self._windows.items():
                expire_ts = float(payload.get("expire_ts") or 0.0)
                remaining = expire_ts - now_ts
                # 只返回即将过期且未跳过活动的窗口
                if remaining <= threshold_seconds and remaining > 0:
                    if not bool(payload.get("skip_activity")):
                        result.append(dict(payload))
        return result

    def mark_window_ending_notified(self, conversation_id: str) -> bool:
        """标记窗口已发送结束通知（避免重复发送）。

        Args:
            conversation_id: 会话 ID

        Returns:
            是否标记成功
        """
        cid = str(conversation_id or "").strip()
        if not cid:
            return False
        snapshot: dict[str, dict[str, Any]] = {}
        with self._lock:
            payload = self._windows.get(cid)
            if not payload:
                return False
            payload["ending_notified"] = True
            snapshot = self._snapshot_locked()
        self._save_to_disk_unlocked(snapshot)
        return True

    def has_window_ending_notified(self, conversation_id: str) -> bool:
        """检查窗口是否已发送结束通知。

        Args:
            conversation_id: 会话 ID

        Returns:
            是否已发送通知
        """
        cid = str(conversation_id or "").strip()
        if not cid:
            return False
        with self._lock:
            payload = self._windows.get(cid)
            if not payload:
                return False
            return bool(payload.get("ending_notified"))


_manager: InterruptWindowManager | None = None
_manager_lock = threading.Lock()


def get_interrupt_window_manager() -> InterruptWindowManager:
    """获取全局手动打断窗口管理器。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = InterruptWindowManager()
    return _manager


def activate_manual_interrupt_window(
    *,
    conversation_id: str,
    role_id: str,
    activity: str,
    window_seconds: float,
    source: str = "manual_interrupt",
    skip_activity: bool = False,
) -> dict[str, Any]:
    """开启手动打断后的聊天窗口。"""
    return get_interrupt_window_manager().activate(
        conversation_id=conversation_id,
        role_id=role_id,
        activity=activity,
        window_seconds=window_seconds,
        source=source,
        skip_activity=skip_activity,
    )


def get_manual_interrupt_window(
    *,
    conversation_id: str,
    role_id: str = "",
) -> dict[str, Any] | None:
    """读取当前仍有效的手动打断窗口。"""
    return get_interrupt_window_manager().get_active(
        conversation_id=conversation_id,
        role_id=role_id,
    )


def extend_manual_interrupt_window(
    *,
    conversation_id: str,
    extend_seconds: float,
    max_extend_count: int = 3,
) -> dict[str, Any] | None:
    """延长手动打断窗口。"""
    return get_interrupt_window_manager().extend(
        conversation_id=conversation_id,
        extend_seconds=extend_seconds,
        max_extend_count=max_extend_count,
    )


def mark_skip_current_activity(
    *,
    conversation_id: str,
) -> dict[str, Any] | None:
    """标记跳过当前活动。"""
    return get_interrupt_window_manager().mark_skip_activity(
        conversation_id=conversation_id,
    )


def clear_manual_interrupt_window(conversation_id: str) -> None:
    """清理某个会话的手动打断窗口。"""
    get_interrupt_window_manager().clear(conversation_id)


def get_expiring_interrupt_windows(
    threshold_seconds: float = 60.0,
) -> list[dict[str, Any]]:
    """获取即将过期的中断窗口列表（用于触发主动消息）。"""
    return get_interrupt_window_manager().get_expiring_windows(
        threshold_seconds=threshold_seconds,
    )


def mark_interrupt_window_ending_notified(conversation_id: str) -> bool:
    """标记中断窗口已发送结束通知。"""
    return get_interrupt_window_manager().mark_window_ending_notified(
        conversation_id=conversation_id,
    )


def has_interrupt_window_ending_notified(conversation_id: str) -> bool:
    """检查中断窗口是否已发送结束通知。"""
    return get_interrupt_window_manager().has_window_ending_notified(
        conversation_id=conversation_id,
    )

