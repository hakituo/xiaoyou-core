#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 InterruptWindowManager 的磁盘持久化：模拟 backend 重启后窗口仍能恢复。

复现 2026-08-03 用户反馈的 bug：
1. 用户 /跳过 创建长窗口（skip=True）
2. backend 重启（改代码/手动重启/崩溃恢复）
3. InterruptWindowManager 是纯内存单例，重启后 _windows 被清空
4. 用户发消息，reply_policy 读不到中断窗口，走 busy_defer_silent 静默累积

修复后期望：
- /跳过 后窗口写入 companion_data/character_daily/interrupt_windows.json
- 重启（重新创建 InterruptWindowManager 实例）后从磁盘恢复未过期窗口
- 原有过期窗口在加载时被过滤
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)


def _make_manager_with_temp_persistence(tmp_dir: Path):
    """创建一个使用临时持久化路径的 InterruptWindowManager。

    通过 patch 模块级 _PERSISTENCE_FILE，让所有读写都指向临时目录，
    避免污染生产数据文件。
    """
    from core.services.character_daily import interrupt_window as iw_mod

    tmp_file = tmp_dir / "interrupt_windows.json"
    with patch.object(iw_mod, "_PERSISTENCE_FILE", tmp_file):
        manager = iw_mod.InterruptWindowManager()
    return manager, tmp_file, iw_mod


def main() -> int:
    cid = "private_123456789__persona__aveline_qq_master"
    role_id = "aveline"
    activity = "studying"
    window_seconds = 3600.0  # 1 小时

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        # ===== 步骤 1: 模拟第一次启动，创建 /跳过 窗口 =====
        print("--- 步骤 1: 第一次启动，activate 创建 skip 窗口 ---")
        manager1, tmp_file, iw_mod = _make_manager_with_temp_persistence(tmp_dir)

        # 使用 patch 让 activate 写到临时路径
        with patch.object(iw_mod, "_PERSISTENCE_FILE", tmp_file):
            payload = iw_mod.activate_manual_interrupt_window(
                conversation_id=cid,
                role_id=role_id,
                activity=activity,
                window_seconds=window_seconds,
                source="qq_command_skip_auto_interrupt",
                skip_activity=True,
            )

        if not payload:
            print("验证失败：activate 返回空")
            return 1
        print(f"activate 成功: expire_ts={payload.get('expire_ts')}, "
              f"skip_activity={payload.get('skip_activity')}")

        # 验证文件已写盘
        if not tmp_file.exists():
            print(f"验证失败：持久化文件未生成: {tmp_file}")
            return 1
        with open(tmp_file, encoding="utf-8") as f:
            disk_data = json.load(f)
        if len(disk_data) != 1:
            print(f"验证失败：磁盘上应有 1 个窗口，实际 {len(disk_data)}")
            return 1
        print(f"持久化文件已写盘: {tmp_file} ({len(disk_data)} 个窗口)")

        # ===== 步骤 2: 模拟重启，新建 manager 实例，应从磁盘恢复 =====
        print("\n--- 步骤 2: 模拟重启，新建 manager 应从磁盘恢复窗口 ---")
        with patch.object(iw_mod, "_PERSISTENCE_FILE", tmp_file):
            manager2 = iw_mod.InterruptWindowManager()

        # 验证窗口已恢复
        restored = iw_mod.get_manual_interrupt_window(
            conversation_id=cid,
            role_id=role_id,
        )
        if not restored:
            print("验证失败：重启后窗口未恢复")
            return 1
        if not restored.get("skip_activity"):
            print(f"验证失败：重启后 skip_activity 标记丢失: {restored}")
            return 1
        remaining = float(restored.get("expire_ts") or 0) - time.time()
        if remaining <= 0:
            print(f"验证失败：重启后窗口已过期: remaining={remaining}s")
            return 1
        print(f"重启后窗口已恢复: skip_activity={restored.get('skip_activity')}, "
              f"remaining={remaining:.1f}s")

        # ===== 步骤 3: 验证 reply_policy 能命中恢复后的窗口 =====
        print("\n--- 步骤 3: 验证 reply_policy 命中恢复后的窗口 ---")
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig
        from core.services.character_daily.reply_policy import evaluate_reply_state

        mock_engine = MagicMock()
        mock_engine.get_current_activity.return_value = ActivityType.STUDYING
        mock_engine.refresh_current_activity.return_value = ActivityType.STUDYING

        mock_ac = MagicMock()
        mock_ac.storage = MagicMock()
        mock_ac.storage.get_proactive_state = AsyncMock(
            return_value={"last_goodnight_ts": 0.0, "last_goodmorning_ts": 0.0}
        )

        async def _check():
            with patch.object(iw_mod, "_PERSISTENCE_FILE", tmp_file), \
                 patch("core.services.character_daily.engine.get_character_daily_engine",
                       return_value=mock_engine), \
                 patch("core.services.active_care.core.service.get_active_care_service",
                       return_value=mock_ac):
                return await evaluate_reply_state(
                    role_id=role_id,
                    config=ReplyPolicyConfig(
                        enabled=True,
                        manual_interrupt_window_seconds=300.0,
                    ),
                    conversation_id=cid,
                )

        decision = asyncio.run(_check())
        if not decision.should_reply:
            print(f"验证失败：reply_policy 未命中重启后的窗口，"
                  f"should_reply={decision.should_reply}, reason={decision.reason}")
            return 1
        if "manual_interrupt_window" not in decision.reason:
            print(f"验证失败：reply_policy 未走中断窗口分支: reason={decision.reason}")
            return 1
        if "skip=True" not in decision.reason:
            print(f"验证失败：skip_activity 标记未传递到 reply_policy: reason={decision.reason}")
            return 1
        print(f"reply_policy 命中中断窗口: should_reply={decision.should_reply}")
        print(f"reason={decision.reason}")

        # ===== 步骤 4: 验证过期窗口在重启时被过滤 =====
        print("\n--- 步骤 4: 验证过期窗口在重启时被过滤 ---")
        # 手动写一个已过期的窗口到磁盘
        expired_data = {
            "private_expired": {
                "conversation_id": "private_expired",
                "role_id": role_id,
                "activity": "studying",
                "window_seconds": 300.0,
                "source": "manual_interrupt",
                "started_ts": time.time() - 1000,
                "expire_ts": time.time() - 100,  # 已过期 100 秒
                "skip_activity": False,
                "extended_count": 0,
            }
        }
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(expired_data, f)

        with patch.object(iw_mod, "_PERSISTENCE_FILE", tmp_file):
            manager3 = iw_mod.InterruptWindowManager()

        # 过期窗口不应被恢复
        expired_window = iw_mod.get_manual_interrupt_window(
            conversation_id="private_expired",
            role_id=role_id,
        )
        if expired_window is not None:
            print(f"验证失败：过期窗口未被过滤: {expired_window}")
            return 1
        print("过期窗口在重启时已被正确过滤")

        # 清理
        with patch.object(iw_mod, "_PERSISTENCE_FILE", tmp_file):
            iw_mod.clear_manual_interrupt_window(cid)

    print("\n验证通过：InterruptWindowManager 持久化工作正常，重启后窗口可恢复。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
