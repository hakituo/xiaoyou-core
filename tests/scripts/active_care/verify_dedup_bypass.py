"""验证短句关怀类（晚安/早安/睡回去）跳过 active_care 去重检测。

验证点：
1. goodnight_proactive：消息与历史锚点高度重复时仍应发送（不返回 None）
2. good_morning_proactive：同上
3. sleep_again_proactive：同上
4. 普通类型（proactive_chat）：相同重复消息应被去重拦截（返回 None）
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestDedupBypassForShortGreetings(unittest.IsolatedAsyncioTestCase):
    """测试短句关怀类 sys_prompt_type 跳过去重。"""

    def _make_postprocessor(self):
        from core.services.active_care.postprocess.postprocessor import (
            ActiveCarePostprocessor,
        )

        return ActiveCarePostprocessor()

    async def _run_postprocess(
        self,
        *,
        sys_prompt_type: str,
        message: str,
        repeat_anchors: list[str],
    ):
        """运行 postprocess 并返回结果（None 表示被拦截）。"""
        pp = self._make_postprocessor()
        # _regenerate_non_repetitive_text 在去重触发时会被调用，
        # 用 Mock 让它返回 None（改写失败），使普通类型被干净拦截
        pp._regenerate_non_repetitive_text = AsyncMock(return_value=None)
        response = {"content": message, "full_content": message, "message_type": "text"}
        result = await pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            sys_prompt_type=sys_prompt_type,
            target_conversation_id="private_10001__persona__aveline_qq_master",
            preferred_language="zh",
            repeat_anchors=repeat_anchors,
            last_user_message="晚安，Master",
            last_proactive_assistant_message="",
            sleep_session_active=False,
            sleep_confirmed_by_silence=False,
            known_sleep_time="",
            now_ts=0.0,
        )
        return result

    async def test_goodnight_proactive_bypasses_dedup(self):
        """goodnight_proactive 即使与历史锚点重复也应发送。"""
        # 这正是线上被误杀的消息：LLM 生成 "晚安，Master。我也要睡了..." 与用户 "晚安，Master" 重复
        message = "晚安，Master。我也要睡了，记得明天起来先吃饭。"
        result = await self._run_postprocess(
            sys_prompt_type="goodnight_proactive",
            message=message,
            repeat_anchors=["晚安，Master"],
        )
        self.assertIsNotNone(result, "晚安消息不应被去重拦截")
        self.assertIn("晚安", result["content"])

    async def test_good_morning_proactive_bypasses_dedup(self):
        """good_morning_proactive 即使与历史锚点重复也应发送。"""
        message = "早安，Master。昨晚睡得好吗？我饿醒了。"
        result = await self._run_postprocess(
            sys_prompt_type="good_morning_proactive",
            message=message,
            repeat_anchors=["早安，Master"],
        )
        self.assertIsNotNone(result, "早安消息不应被去重拦截")
        self.assertIn("早安", result["content"])

    async def test_sleep_again_proactive_bypasses_dedup(self):
        """sleep_again_proactive 即使与历史锚点重复也应发送。"""
        message = "我又困了，先去睡了。你也早点睡吧，Master。"
        result = await self._run_postprocess(
            sys_prompt_type="sleep_again_proactive",
            message=message,
            repeat_anchors=["我又困了，先去睡了"],
        )
        self.assertIsNotNone(result, "睡回去消息不应被去重拦截")

    async def test_normal_type_still_blocked_by_dedup(self):
        """普通 proactive_chat 类型应被去重拦截（确认 bypass 只影响短句关怀类）。

        用完全重复的锚点（anchor 等于整条消息）确保语义去重必然触发。
        """
        message = "晚安，Master。我也要睡了，记得明天起来先吃饭。"
        result = await self._run_postprocess(
            sys_prompt_type="proactive_chat",
            message=message,
            repeat_anchors=[message],  # 完全重复，必然触发整句语义去重
        )
        # 普通类型完全重复消息应被拦截（返回 None）
        self.assertIsNone(result, "普通类型重复消息应被去重拦截")


if __name__ == "__main__":
    unittest.main(verbosity=2)
