from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

from core.utils.logger import get_module_logger

logger = get_module_logger(__name__, "nightly_processor.log")

EXCLUDED_USER_PREFIXES = ("test_", "sensitive_test_", "auto_heal_", "default")


def check_user_sleeping() -> bool:
    """检查用户是否正在睡觉。"""
    try:
        from core.services.active_care.shared.constants import StateKeys
        from core.services.active_care.storage.storage import ActiveCareStorage

        storage = ActiveCareStorage()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            state = loop.run_until_complete(storage.get_proactive_state())
            if not state:
                return False

            reduced_mode_active = state.get(StateKeys.REDUCED_MODE_ACTIVE, False)
            reduced_mode_label = state.get(StateKeys.REDUCED_MODE_LABEL, "")
            return reduced_mode_active and reduced_mode_label == "sleep"
        finally:
            loop.close()
    except Exception as exc:
        logger.warning(f"检查用户睡眠状态失败: {exc}")
        return False


def load_users_from_disk() -> Dict[str, Any]:
    """从磁盘扫描已有用户并加载记忆管理器实例。"""
    from memory.weighted_memory_manager import get_weighted_memory_manager

    loaded_managers: Dict[str, Any] = {}
    seen_scopes: set[str] = set()
    data_dirs = [
        Path("companion_data/aveline_data/memories/weighted"),
        Path("companion_data/ling_data/memories/weighted"),
    ]

    for data_dir in data_dirs:
        if not data_dir.exists():
            continue

        # 统一扫描全部加权记忆 scope。旧逻辑只认 __scope__ 和三个固定名称，
        # 冷启动时会漏掉 private_xxx_weighted.json 这类真实用户主 scope。
        for weighted_file in data_dir.glob("*_weighted.json"):
            user_id = weighted_file.name.replace("_weighted.json", "")
            try:
                if weighted_file.stat().st_size < 100 or user_id in seen_scopes:
                    continue
            except Exception:
                continue

            seen_scopes.add(user_id)
            try:
                loaded_managers[user_id] = get_weighted_memory_manager(user_id)
                logger.info(f"从磁盘加载用户: {user_id}")
            except Exception as exc:
                logger.warning(f"加载用户 {user_id} 失败: {exc}")

    logger.info(f"从磁盘加载了 {len(loaded_managers)} 个用户")
    return loaded_managers


def filter_real_users(memory_managers: Dict[str, Any]) -> Dict[str, Any]:
    """过滤掉测试用户与系统保留用户。"""
    return {
        user_id: manager
        for user_id, manager in memory_managers.items()
        if not user_id.startswith(EXCLUDED_USER_PREFIXES)
    }
