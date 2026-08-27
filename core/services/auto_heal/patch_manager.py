import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.services.auto_heal.models import (
    Patch,
    PatchStatus,
)
from core.utils.logger import get_logger

logger = get_logger("PatchManager")

_MAX_PATCH_SIZE_BYTES = 512 * 1024
_MAX_DAILY_PATCHES = 10
_MAX_PATCHES_PER_FILE = 3
# P1-5: 持久化补丁元数据（含 status/root_cause/rollback_code），
# 进程重启后保留待审批补丁、回滚能力、每日/单文件配额计数
_STATE_FILE_NAME = "patches_state.json"
_MAX_PERSISTED_PATCHES = 200  # 防止无界增长

_PROTECTED_FILES = {
    "main.py",
    "core/core_engine/lifecycle_manager.py",
    "core/core_engine/event_bus.py",
    "core/lifecycle/lifespan.py",
    "core/services/auto_heal/heal_service.py",
    "core/services/auto_heal/anomaly_detector.py",
    "core/services/auto_heal/patch_generator.py",
    "core/services/auto_heal/patch_sandbox.py",
    "core/services/auto_heal/root_cause_analyzer.py",
    "core/services/auto_heal/models.py",
    "core/utils/logger.py",
    "core/utils/log_sanitizer.py",
    "core/utils/error_handler.py",
    "config/integrated_config.py",
}


class PatchManager:
    """补丁管理器，负责补丁的生成、验证、应用和回滚"""

    def __init__(self):
        self._patches: Dict[str, Patch] = {}
        self._daily_patch_count: int = 0
        self._daily_patch_reset_ts: float = 0.0
        self._file_patch_counts: Dict[str, int] = {}
        self._heal_count: int = 0
        # P1-5: 启动时加载持久化状态，恢复待审批补丁和配额计数
        self._state_file: Optional[Path] = self._resolve_state_file()
        self._load_state_sync()

    @classmethod
    def _resolve_state_file(cls) -> Optional[Path]:
        """解析持久化文件路径：{project_root}/logs/auto_heal/patches_state.json"""
        try:
            from core.utils.common import get_project_root

            return Path(get_project_root()) / "logs" / "auto_heal" / _STATE_FILE_NAME
        except Exception:
            return None

    def _load_state_sync(self) -> None:
        """P1-5: 启动时从磁盘加载补丁状态（同步执行，__init__ 中调用）"""
        if not self._state_file or not self._state_file.exists():
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            patches_data = data.get("patches") or []
            for p_dict in patches_data:
                try:
                    patch = Patch.from_dict(p_dict)
                    if patch.id:
                        self._patches[patch.id] = patch
                except Exception as e:
                    logger.warning("加载补丁失败（跳过该条）: %s", e)
            self._daily_patch_count = int(data.get("daily_patch_count", 0) or 0)
            self._daily_patch_reset_ts = float(data.get("daily_patch_reset_ts", 0) or 0)
            self._file_patch_counts = {
                str(k): int(v) for k, v in (data.get("file_patch_counts") or {}).items()
            }
            self._heal_count = int(data.get("heal_count", 0) or 0)
            logger.info(
                "PatchManager 已加载持久化状态: %d 个补丁, daily=%d, heal=%d",
                len(self._patches), self._daily_patch_count, self._heal_count,
            )
        except Exception as e:
            logger.warning("加载补丁状态失败（忽略，使用空状态）: %s", e)

    async def _save_state_async(self) -> None:
        """P1-5: 异步原子写入补丁状态到磁盘"""
        if not self._state_file:
            return
        try:
            # 只持久化最近 N 条，按 created_at 降序
            sorted_patches = sorted(
                self._patches.values(), key=lambda p: p.created_at, reverse=True
            )[:_MAX_PERSISTED_PATCHES]
            data = {
                "patches": [p.to_dict() for p in sorted_patches],
                "daily_patch_count": self._daily_patch_count,
                "daily_patch_reset_ts": self._daily_patch_reset_ts,
                "file_patch_counts": dict(self._file_patch_counts),
                "heal_count": self._heal_count,
                "saved_at": time.time(),
            }

            def _write_atomic():
                self._state_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = str(self._state_file) + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp_path, self._state_file)  # 原子替换

            await asyncio.to_thread(_write_atomic)
        except Exception as e:
            logger.warning("保存补丁状态失败: %s", e)

    def register_patch(self, patch: Patch) -> None:
        """P1-5: 注册补丁到管理器（替代外部直接操作 patches 字典）

        注意：此方法是同步的，仅更新内存。调用方应在 await 完成后
        调用 `_save_state_async()` 持久化；或在状态变更点统一调用。
        """
        if not patch or not patch.id:
            return
        self._patches[patch.id] = patch

    @property
    def patches(self) -> Dict[str, Patch]:
        return self._patches

    @property
    def heal_count(self) -> int:
        return self._heal_count

    @property
    def daily_patch_count(self) -> int:
        return self._daily_patch_count

    def check_daily_limit(self) -> bool:
        """检查每日补丁数量限制"""
        now = time.time()
        if now - self._daily_patch_reset_ts > 86400:
            self._daily_patch_count = 0
            self._daily_patch_reset_ts = now
            self._file_patch_counts.clear()
        return self._daily_patch_count < _MAX_DAILY_PATCHES

    def check_file_limit(self, file_path: str) -> bool:
        """检查单文件补丁数量限制"""
        count = self._file_patch_counts.get(file_path, 0)
        return count < _MAX_PATCHES_PER_FILE

    def is_protected_file(self, file_path: str) -> bool:
        """检查是否为受保护文件"""
        normalized = file_path.replace("\\", "/")
        for protected in _PROTECTED_FILES:
            if normalized == protected or normalized.endswith("/" + protected):
                return True
        return False

    async def apply_patch(self, patch_id: str) -> Dict[str, Any]:
        """应用补丁"""
        patch = self._patches.get(patch_id)
        if patch is None:
            return {"success": False, "message": "补丁不存在"}

        if patch.status not in (
            PatchStatus.AWAITING_APPROVAL,
            PatchStatus.APPROVED,
        ):
            return {"success": False, "message": f"补丁状态不允许应用: {patch.status.value}"}

        if self.is_protected_file(patch.file_path):
            patch.status = PatchStatus.FAILED
            return {"success": False, "message": f"受保护文件，禁止修改: {patch.file_path}"}

        if not self.check_daily_limit():
            return {"success": False, "message": f"今日补丁数量已达上限({_MAX_DAILY_PATCHES})"}

        try:
            from core.utils.common import get_project_root

            project_root = Path(get_project_root())
        except Exception:
            project_root = Path(__file__).parent.parent.parent.parent

        file_path = project_root / patch.file_path
        if not file_path.exists():
            patch.status = PatchStatus.FAILED
            return {"success": False, "message": f"文件不存在: {patch.file_path}"}

        try:
            backup_path = str(file_path) + ".auto_heal_backup"

            await asyncio.to_thread(
                self._write_file, backup_path, patch.original_code
            )

            backup_ok = await asyncio.to_thread(self._verify_backup, backup_path, patch.original_code)
            if not backup_ok:
                logger.error(f"备份验证失败，中止应用: {backup_path}")
                patch.status = PatchStatus.FAILED
                return {"success": False, "message": "备份验证失败，为安全起见中止操作"}

            await asyncio.to_thread(
                self._write_file, str(file_path), patch.patched_code
            )

            patch.status = PatchStatus.APPLIED
            patch.applied_at = time.time()
            self._heal_count += 1
            self._daily_patch_count += 1
            self._file_patch_counts[patch.file_path] = (
                self._file_patch_counts.get(patch.file_path, 0) + 1
            )

            logger.info(f"补丁已应用: {patch.file_path} (补丁ID: {patch.id})")
            # P1-5: 状态变更后持久化（配额计数 + 补丁状态）
            await self._save_state_async()

            return {
                "success": True,
                "message": f"补丁已应用到 {patch.file_path}",
                "patch_id": patch.id,
                "file_path": patch.file_path,
            }
        except Exception as e:
            patch.status = PatchStatus.FAILED
            logger.error(f"应用补丁失败: {e}", exc_info=True)
            # P1-5: 失败状态也持久化，避免重启后误以为仍在 AWAITING_APPROVAL
            await self._save_state_async()

            try:
                await asyncio.to_thread(
                    self._write_file, str(file_path), patch.original_code
                )
                logger.info(f"已自动恢复原文件: {patch.file_path}")
            except Exception as restore_err:
                logger.critical(
                    f"自动恢复失败！请手动从备份恢复: {backup_path}，错误: {restore_err}"
                )

            return {"success": False, "message": f"应用失败: {e}"}

    async def rollback_patch(self, patch_id: str) -> Dict[str, Any]:
        """回滚补丁"""
        patch = self._patches.get(patch_id)
        if patch is None:
            return {"success": False, "message": "补丁不存在"}

        if patch.status != PatchStatus.APPLIED:
            return {"success": False, "message": "只能回滚已应用的补丁"}

        try:
            from core.utils.common import get_project_root

            project_root = Path(get_project_root())
        except Exception:
            project_root = Path(__file__).parent.parent.parent.parent

        file_path = project_root / patch.file_path
        backup_path = str(file_path) + ".auto_heal_backup"

        try:
            if patch.rollback_code:
                await asyncio.to_thread(
                    self._write_file, str(file_path), patch.rollback_code
                )
            elif Path(backup_path).exists():
                backup_content = await asyncio.to_thread(
                    Path(backup_path).read_text, "utf-8"
                )
                await asyncio.to_thread(
                    self._write_file, str(file_path), backup_content
                )
                logger.info(f"从备份文件恢复: {backup_path}")
            else:
                return {"success": False, "message": "无回滚代码且备份文件不存在"}

            patch.status = PatchStatus.ROLLED_BACK
            logger.info(f"补丁已回滚: {patch.file_path}")
            # P1-5: 回滚后持久化（避免重启后被误认为已应用）
            await self._save_state_async()

            return {
                "success": True,
                "message": f"补丁已回滚: {patch.file_path}",
                "patch_id": patch.id,
            }
        except Exception as e:
            logger.critical(f"回滚补丁失败！请手动恢复: {backup_path}，错误: {e}", exc_info=True)
            return {"success": False, "message": f"回滚失败，请手动从备份恢复: {backup_path}"}

    async def reject_patch(self, patch_id: str) -> Dict[str, Any]:
        """拒绝补丁"""
        patch = self._patches.get(patch_id)
        if patch is None:
            return {"success": False, "message": "补丁不存在"}

        patch.status = PatchStatus.REJECTED
        # P1-5: 状态变更后持久化（避免重启后又被误以为待审批）
        await self._save_state_async()
        return {"success": True, "message": "补丁已拒绝"}

    def get_pending_patches(self) -> List[Dict[str, Any]]:
        """获取待审批补丁"""
        result = []
        for patch in self._patches.values():
            if patch.status == PatchStatus.AWAITING_APPROVAL:
                result.append(self._patch_to_dict(patch))
        return result

    def get_all_patches(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取所有补丁"""
        patches = sorted(
            self._patches.values(), key=lambda p: p.created_at, reverse=True
        )
        return [self._patch_to_dict(p) for p in patches[:limit]]

    def get_patch_detail(self, patch_id: str) -> Optional[Dict[str, Any]]:
        """获取补丁详情"""
        patch = self._patches.get(patch_id)
        if patch is None:
            return None
        return self._patch_to_dict(patch, include_code=True)

    def _patch_to_dict(self, patch: Patch, include_code: bool = False) -> Dict[str, Any]:
        """将补丁对象转换为字典"""
        d: Dict[str, Any] = {
            "id": patch.id,
            "anomaly_id": patch.anomaly_id,
            "file_path": patch.file_path,
            "description": patch.description,
            "status": patch.status.value,
            "created_at": patch.created_at,
            "applied_at": patch.applied_at,
            "verified": patch.verified,
            "verification_result": patch.verification_result,
        }
        if include_code:
            d["diff"] = patch.diff
            d["original_code"] = patch.original_code[:3000]
            d["patched_code"] = patch.patched_code[:3000]
            if patch.root_cause:
                d["root_cause"] = {
                    "file_path": patch.root_cause.file_path,
                    "start_line": patch.root_cause.start_line,
                    "end_line": patch.root_cause.end_line,
                    "analysis": patch.root_cause.analysis,
                    "confidence": patch.root_cause.confidence,
                }
        return d

    @staticmethod
    def _write_file(path: str, content: str):
        """写入文件"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _verify_backup(backup_path: str, expected_content: str) -> bool:
        """验证备份文件"""
        try:
            actual = Path(backup_path).read_text(encoding="utf-8")
            return actual == expected_content
        except Exception:
            return False
