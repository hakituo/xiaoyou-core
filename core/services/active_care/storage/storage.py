import os
import json
import asyncio
import aiofiles
from typing import Any, Dict, Optional
from core.utils.logger import get_logger
from core.utils.async_locks import LazyAsyncLock
from config.debug_config import is_debug_enabled
from core.utils.data_paths import get_active_care_dir
from config.integrated_config import get_settings
from core.services.active_care.shared.constants import (
    StateKeys,
    normalize_persona_token,
    extract_persona_token,
)
from core.utils.timestamp_utils import safe_timestamp

logger = get_logger("ACTIVE_CARE_STORAGE")


class ActiveCareStorage:
    _USER_SLEEP_STATE_FILENAME = "user_sleep_state.json"
    _SLEEP_MODE_REASONS = {"goodnight", "sleep_hint", "sleep"}
    _USER_SLEEP_STATE_KEYS = {
        StateKeys.LAST_GOODNIGHT_TS,
        StateKeys.LAST_GOODMORNING_TS,
        StateKeys.LAST_GOODNIGHT_PROBE_TS,
        StateKeys.LAST_SLEEP_SESSION_START_TS,
        StateKeys.LAST_SLEEP_SESSION_END_TS,
        StateKeys.LAST_SLEEP_SESSION_DURATION_SECONDS,
        StateKeys.LAST_SLEEP_SESSION_SOURCE,
        StateKeys.LAST_SLEEP_SESSION_KIND,
        StateKeys.LAST_LOW_DISTURBANCE_EXIT_TS,
        StateKeys.LAST_LOW_DISTURBANCE_EXIT_SOURCE,
        StateKeys.GOODNIGHT_BUT_AWAKE_TS,
        StateKeys.GOODNIGHT_BUT_AWAKE_ELAPSED,
        StateKeys.LAST_GOODNIGHT_SUMMARY_DATE,
        StateKeys.LAST_GOODNIGHT_SUMMARY_TS,
        StateKeys.REDUCED_MODE_ACTIVE,
        StateKeys.REDUCED_MODE_REASON,
        StateKeys.REDUCED_MODE_LABEL,
        StateKeys.REDUCED_MODE_STARTED_TS,
        StateKeys.REDUCED_MODE_EXPECTED_END_TS,
    }

    def __init__(self):
        self.settings = get_settings()
        self._proactive_state_cache = None
        self._user_sleep_state_cache = None
        self._policy_scores = {}
        self._proactive_count_cache = None
        self._runtime_scope = "aveline"
        # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._file_lock = LazyAsyncLock()
        self._pending_updates: Dict[str, Any] = {}
        self._flush_task: Optional[asyncio.Task] = None
        self._flush_interval = 2.0
        self._dirty = False

    def _normalize_persona_token_from_filename(self, filename: str) -> str:
        return normalize_persona_token(filename)

    def _extract_persona_token(self, conversation_id: str) -> str:
        return extract_persona_token(conversation_id)

    def set_runtime_scope(self, scope: str) -> None:
        value = str(scope or "").strip().lower()
        if not value:
            value = "aveline"
        if value != self._runtime_scope:
            self._runtime_scope = value
            self._proactive_state_cache = None
            self._policy_scores = {}
            self._proactive_count_cache = None

    def get_runtime_scope(self) -> str:
        return self._runtime_scope

    def resolve_scope_from_persona_filename(self, persona_filename: str) -> str:
        """根据 persona_filename 解析 scope（用于多QQ模式）

        yeye/rushuang 已接入独立 QQ 账号并参与 active_care；xiaolu/mianmian 仅接
        character_daily + sleep_manager。都返回它们自己的 scope，避免误用 aveline
        的睡眠/活动状态。
        """
        fn = str(persona_filename or "").strip().lower()
        if "ling" in fn:
            return "ling"
        if "aveline" in fn or "澪" in fn:
            return "aveline"
        if "yeye" in fn or "Coco" in fn or "susuomu" in fn:
            return "yeye"
        if "xiaolu" in fn or "小鹿" in fn:
            return "xiaolu"
        if "rushuang" in fn or "Frost" in fn or "shenrushuang" in fn:
            return "rushuang"
        if "mianmian" in fn or "Mian" in fn or "yemian" in fn or "叶眠" in fn:
            return "mianmian"
        if "chiba" in fn or "Chiba" in fn or "千葉" in fn:
            return "chiba"
        token = normalize_persona_token(persona_filename)
        if "ling" in token:
            return "ling"
        if "yeye" in token:
            return "yeye"
        if "xiaolu" in token:
            return "xiaolu"
        if "rushuang" in token or "Frost" in token:
            return "rushuang"
        if "mianmian" in token or "Mian" in token or "叶眠" in token:
            return "mianmian"
        if "chiba" in token or "Chiba" in token or "千葉" in token:
            return "chiba"
        return "aveline"

    def resolve_scope_from_conversation_id(self, conversation_id: str) -> str:
        cid = str(conversation_id or "").strip()
        cid_lower = cid.lower()
        # 处理 resolve_memory_user_id 生成的 scope 格式：xxx__scope__<scope_name>
        if "__scope__" in cid_lower:
            scope_part = cid_lower.split("__scope__", 1)[1].strip("_")
            if scope_part in {"ling", "yeye", "xiaolu", "rushuang", "mianmian", "chiba"}:
                return scope_part
            return "aveline"
        # QQ 官方机器人会话后缀（__persona__xxx）直接识别
        if "__persona__yeye" in cid_lower or "_yeye" in cid_lower:
            return "yeye"
        if "__persona__xiaolu" in cid_lower or "_xiaolu" in cid_lower:
            return "xiaolu"
        if "__persona__rushuang" in cid_lower or "_rushuang" in cid_lower:
            return "rushuang"
        if "__persona__mianmian" in cid_lower or "_mianmian" in cid_lower:
            return "mianmian"
        if "__persona__chiba" in cid_lower or "_chiba" in cid_lower:
            return "chiba"
        # 中文 persona 文件名（如 __persona__Frost / __persona__Mian）
        if "__persona__Frost" in cid or "_Frost" in cid:
            return "rushuang"
        if "__persona__Mian" in cid or "_Mian" in cid:
            return "mianmian"
        if "__persona__Chiba" in cid or "_Chiba" in cid:
            return "chiba"
        token = self._extract_persona_token(cid)
        if not token:
            return "aveline"
        if (
            token.endswith("core_ling")
            or token in {"core_ling", "ling", "wang_ling"}
            or str(cid).lower().endswith("__ling")
            or "_ling" in str(cid).lower()
        ):
            return "ling"
        if token in {"yeye", "qq_yeye"} or "_yeye" in str(cid).lower():
            return "yeye"
        if token in {"xiaolu", "qq_xiaolu"} or "_xiaolu" in str(cid).lower():
            return "xiaolu"
        if token in {"rushuang", "qq_rushuang", "Frost"} or "_rushuang" in str(cid).lower():
            return "rushuang"
        if token in {"mianmian", "qq_mianmian", "Mian"} or "_mianmian" in str(cid).lower():
            return "mianmian"
        if token in {"chiba", "qq_chiba", "Chiba", "千葉"} or "_chiba" in str(cid).lower():
            return "chiba"
        try:
            from core.character.managers.persona_manager import get_persona_manager

            pm = get_persona_manager()
            for item in pm.list_personas():
                filename = str((item or {}).get("filename") or "").strip()
                if not filename:
                    continue
                if self._normalize_persona_token_from_filename(filename) != token:
                    continue
                cfg = pm.get_persona_by_filename(filename) or {}
                identity = cfg.get("identity") if isinstance(cfg, dict) else {}
                name = (
                    str((identity or {}).get("cn_name") or "")
                    + " "
                    + str((identity or {}).get("name") or "")
                ).lower()
                if "Ling" in name or "ling" in name:
                    return "ling"
                if "Coco" in name or "yeye" in name or "苏沐晴" in name:
                    return "yeye"
                if "小鹿" in name or "xiaolu" in name or "林知夏" in name:
                    return "xiaolu"
                if "Frost" in name or "rushuang" in name or "沈Frost" in name:
                    return "rushuang"
                if "Mian" in name or "mianmian" in name or "叶眠" in name:
                    return "mianmian"
                if "Chiba" in name or "千葉" in name or "chiba" in name:
                    return "chiba"
                return "aveline"
        except Exception:
            pass
        return "aveline"

    def _get_runtime_dir(self, scope: Optional[str] = None) -> str:
        """获取运行时目录

        Args:
            scope: 可选的 scope，传入时使用该 scope 而非实例级 _runtime_scope。
                   用于并发场景下避免实例状态污染（如 user_response_handler 与 proactive_checker 并发）。
        """
        effective_scope = scope if scope is not None else self._runtime_scope
        base = get_active_care_dir(effective_scope)
        runtime_dir = str(base)
        os.makedirs(runtime_dir, exist_ok=True)
        return runtime_dir

    async def get_last_thought(self) -> Dict[str, str]:
        """异步获取最近的 Active Care 想法和发送内容（供动态上下文使用）"""
        try:
            if self._proactive_state_cache is not None:
                state = self._proactive_state_cache
            else:
                state = await self.get_proactive_state()
            last_thought = str(state.get("last_thought") or "").strip()
            if not last_thought:
                return {}
            return {
                "last_thought": last_thought,
                "last_sent_content": str(state.get("last_sent_content") or "").strip(),
                "last_sent_type": str(state.get("last_sent_type") or "").strip(),
            }
        except Exception:
            return {}

    def get_last_thought_sync(self) -> Dict[str, str]:
        """同步获取最近的 Active Care 想法和发送内容（向后兼容，优先使用 get_last_thought）"""
        try:
            if self._proactive_state_cache is not None:
                state = self._proactive_state_cache
            else:
                state_file = os.path.join(self._get_runtime_dir(), "proactive_state.json")
                if not os.path.exists(state_file):
                    return {}
                import json as _json
                with open(state_file, "r", encoding="utf-8") as f:
                    state = _json.load(f)
                self._proactive_state_cache = state
            last_thought = str(state.get("last_thought") or "").strip()
            if not last_thought:
                return {}
            return {
                "last_thought": last_thought,
                "last_sent_content": str(state.get("last_sent_content") or "").strip(),
                "last_sent_type": str(state.get("last_sent_type") or "").strip(),
            }
        except Exception:
            return {}

    async def _read_json_file(self, filepath: str) -> Dict[str, Any]:
        try:
            if not os.path.exists(filepath):
                return {}
            async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                raw = await f.read()
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            logger.warning(f"Active Care Storage: JSON decode error in {filepath}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Active Care Storage: Failed to read {filepath}: {e}")
            return {}

    async def read_json_file(self, filepath: str) -> Dict[str, Any]:
        """公开接口：读取 JSON 文件"""
        return await self._read_json_file(filepath)

    async def _write_json_file(self, filepath: str, data: Dict[str, Any]) -> None:
        async with self._file_lock:
            await self._write_json_file_unlocked(filepath, data)

    async def _write_json_file_unlocked(self, filepath: str, data: Dict[str, Any]) -> None:
        """使用统一的原子写入模块"""
        from core.utils.atomic_io import async_safe_json_dump
        try:
            await async_safe_json_dump(data, filepath, use_fsync=True)
        except Exception as e:
            logger.warning(f"Active Care Storage: 写入文件失败 {filepath}: {e}")

    async def write_json_file(self, filepath: str, data: Dict[str, Any]) -> None:
        """公开接口：写入 JSON 文件"""
        await self._write_json_file(filepath, data)

    async def get_proactive_state(self, scope: Optional[str] = None) -> Dict[str, Any]:
        """Get proactive state, using cache if available

        Args:
            scope: 可选的 scope。传入时不使用实例缓存，直接读取对应 scope 的文件，
                   避免并发场景下实例级 _runtime_scope 被污染导致读到错误 scope 的状态。
        """
        # 显式传入 scope 时，绕过缓存直接读文件（并发安全路径）
        if scope is not None:
            state_file = os.path.join(self._get_runtime_dir(scope), "proactive_state.json")
            if os.path.exists(state_file):
                try:
                    state = await self._read_json_file(state_file)
                    return await self._merge_user_sleep_state(state)
                except Exception:
                    return {}
            return await self._merge_user_sleep_state({})

        if self._proactive_state_cache is not None:
            return await self._merge_user_sleep_state(self._proactive_state_cache)

        state_file = os.path.join(self._get_runtime_dir(), "proactive_state.json")
        if os.path.exists(state_file):
            try:
                self._proactive_state_cache = await self._read_json_file(state_file)
            except Exception:
                self._proactive_state_cache = {}
        else:
            self._proactive_state_cache = {}

        return await self._merge_user_sleep_state(self._proactive_state_cache)

    def _get_user_sleep_state_file(self) -> str:
        runtime_dir = str(get_active_care_dir("user"))
        os.makedirs(runtime_dir, exist_ok=True)
        return os.path.join(runtime_dir, self._USER_SLEEP_STATE_FILENAME)

    async def get_user_sleep_state(self) -> Dict[str, Any]:
        """读取用户级睡眠状态。

        睡眠/清醒属于用户事实，不属于任何 persona。首次升级时若尚无用户级
        文件，会从现有角色状态中选择时间最新的一份完成兼容迁移。
        """
        if self._user_sleep_state_cache is not None:
            return dict(self._user_sleep_state_cache)

        state_file = self._get_user_sleep_state_file()
        if os.path.exists(state_file):
            state = await self._read_json_file(state_file)
        else:
            state = await self._bootstrap_user_sleep_state()
            if state:
                await self._write_json_file(state_file, state)
                logger.info("Active Care Storage: 已迁移用户级睡眠状态")
        self._user_sleep_state_cache = dict(state or {})
        return dict(self._user_sleep_state_cache)

    async def save_user_sleep_state(
        self,
        updates: Dict[str, Any],
        *,
        immediate: bool = True,
        scope: Optional[str] = None,
        mirror_persona: bool = True,
    ) -> Dict[str, Any]:
        """保存用户级睡眠状态，并兼容镜像到当前 persona 状态。

        用户级文件是权威来源；persona 镜像仅用于兼容仍直接读取旧
        ``proactive_state.json`` 的外围模块，不承担跨角色同步。
        """
        sleep_updates = {
            key: value
            for key, value in dict(updates or {}).items()
            if key in self._USER_SLEEP_STATE_KEYS
        }
        current = await self.get_user_sleep_state()
        current.update(sleep_updates)
        await self._write_json_file(self._get_user_sleep_state_file(), current)
        self._user_sleep_state_cache = dict(current)

        if mirror_persona:
            await self.save_proactive_state(
                dict(updates or {}),
                immediate=immediate,
                scope=scope,
            )
        return await self._merge_user_sleep_state(current)

    async def _merge_user_sleep_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """把用户级睡眠事实覆盖到 persona 状态，保留 persona 专属专注模式。"""
        merged = dict(state or {})
        user_sleep = await self.get_user_sleep_state()
        if not user_sleep:
            return merged

        mode_keys = {
            StateKeys.REDUCED_MODE_ACTIVE,
            StateKeys.REDUCED_MODE_REASON,
            StateKeys.REDUCED_MODE_LABEL,
            StateKeys.REDUCED_MODE_STARTED_TS,
            StateKeys.REDUCED_MODE_EXPECTED_END_TS,
        }
        for key in self._USER_SLEEP_STATE_KEYS - mode_keys:
            if key in user_sleep:
                merged[key] = user_sleep[key]

        global_reason = str(user_sleep.get(StateKeys.REDUCED_MODE_REASON) or "none")
        local_reason = str(merged.get(StateKeys.REDUCED_MODE_REASON) or "none")
        global_sleep_active = bool(user_sleep.get(StateKeys.REDUCED_MODE_ACTIVE)) and (
            global_reason in self._SLEEP_MODE_REASONS
        )
        if global_sleep_active:
            for key in mode_keys:
                merged[key] = user_sleep.get(key)
        elif local_reason in self._SLEEP_MODE_REASONS:
            # 用户已醒时清除角色文件中残留的睡眠 reduced mode；focus 等角色模式保留。
            merged[StateKeys.REDUCED_MODE_ACTIVE] = False
            merged[StateKeys.REDUCED_MODE_REASON] = "none"
            merged[StateKeys.REDUCED_MODE_LABEL] = ""
            merged[StateKeys.REDUCED_MODE_STARTED_TS] = 0.0
            merged[StateKeys.REDUCED_MODE_EXPECTED_END_TS] = 0.0
        return merged

    async def _bootstrap_user_sleep_state(self) -> Dict[str, Any]:
        """从升级前的 persona 状态中选取最新用户睡眠事件。"""
        scopes = {"aveline", "ling", "yeye", "xiaolu", "rushuang", "mianmian", "chiba"}
        try:
            from core.utils.scope_registry import list_dynamic_scopes

            scopes.update(list_dynamic_scopes().keys())
        except Exception:
            pass

        best_state: Dict[str, Any] = {}
        best_ts = 0.0
        for candidate_scope in sorted(scopes):
            state_file = os.path.join(
                self._get_runtime_dir(candidate_scope), "proactive_state.json"
            )
            if not os.path.exists(state_file):
                continue
            candidate = await self._read_json_file(state_file)
            event_ts = max(
                safe_timestamp(candidate.get(StateKeys.LAST_GOODNIGHT_TS)),
                safe_timestamp(candidate.get(StateKeys.LAST_GOODMORNING_TS)),
                safe_timestamp(candidate.get(StateKeys.LAST_SLEEP_SESSION_END_TS)),
            )
            if event_ts < best_ts:
                continue
            best_ts = event_ts
            best_state = {
                key: value
                for key, value in candidate.items()
                if key in self._USER_SLEEP_STATE_KEYS
            }
        return best_state

    async def save_proactive_state(self, updates: Dict[str, Any], immediate: bool = False, scope: Optional[str] = None) -> Dict[str, Any]:
        """更新缓存并保存到文件，返回更新后的状态

        Args:
            updates: 要更新的键值对
            immediate: 是否立即写入磁盘。默认 False 使用延迟写入缓冲，
                       关键状态变更（如睡眠/起床）应使用 immediate=True
            scope: 可选的 scope。传入时不使用实例缓存和延迟写入，
                   直接读取-合并-写入对应 scope 的文件，避免并发场景下
                   实例级 _runtime_scope 被污染导致写到错误 scope 的目录。
        """
        # 显式传入 scope 时，走并发安全的独立路径（不污染实例缓存）
        if scope is not None:
            state_file = os.path.join(self._get_runtime_dir(scope), "proactive_state.json")
            # 读取当前状态
            if os.path.exists(state_file):
                try:
                    current_state = await self._read_json_file(state_file)
                except Exception:
                    current_state = {}
            else:
                current_state = {}
            # 合并更新
            current_state.update(updates)
            # 空数据时跳过写入，已有文件则删除
            if not current_state:
                if os.path.exists(state_file):
                    os.remove(state_file)
                return current_state
            await self._write_json_file(state_file, current_state)
            return current_state

        if self._proactive_state_cache is None:
            state_file = os.path.join(self._get_runtime_dir(), "proactive_state.json")
            if os.path.exists(state_file):
                try:
                    self._proactive_state_cache = await self._read_json_file(state_file)
                except Exception:
                    self._proactive_state_cache = {}
            else:
                self._proactive_state_cache = {}

        self._proactive_state_cache.update(updates)
        self._pending_updates.update(updates)
        self._dirty = True

        if immediate:
            await self._flush_pending_updates()
        else:
            self._ensure_flush_task()

        return self._proactive_state_cache

    def _ensure_flush_task(self):
        """确保延迟写入任务存在"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = loop.create_task(self._delayed_flush())

    async def _delayed_flush(self):
        """延迟写入：等待一小段时间后批量写入磁盘"""
        await asyncio.sleep(self._flush_interval)
        await self._flush_pending_updates()

    async def _flush_pending_updates(self):
        """将待写入的更新刷入磁盘"""
        if not self._dirty:
            return
        async with self._file_lock:
            if not self._dirty:
                return
            self._dirty = False
            state = self._proactive_state_cache
            if state is None:
                return
            state_file = os.path.join(self._get_runtime_dir(), "proactive_state.json")
            if not state:
                # 空数据时跳过写入，已有文件则删除
                if os.path.exists(state_file):
                    os.remove(state_file)
            else:
                await self._write_json_file_unlocked(state_file, state)
            self._pending_updates.clear()

    async def load_policy_scores(self) -> Dict[str, Any]:
        """从磁盘加载 Bandit 策略分值"""
        from core.utils.error_handler import error_handling

        async with error_handling(default_return={}, log_level="warning"):
            score_file = os.path.join(
                self._get_runtime_dir(), "active_care_policy.json"
            )
            if os.path.exists(score_file):
                async with aiofiles.open(score_file, "r", encoding="utf-8") as f:
                    content = await f.read()
                    if content.strip():
                        self._policy_scores = json.loads(content)
                        logger.info(
                            f"Active Care: 已从磁盘加载 {len(self._policy_scores)} 个策略分值"
                        )
        return self._policy_scores

    async def save_policy_scores(self, scores: Dict[str, Any]) -> None:
        """将 Bandit 策略分值保存到磁盘"""
        from core.utils.error_handler import error_handling

        async with error_handling(default_return=None, log_level="error"):
            self._policy_scores = scores
            score_file = os.path.join(
                self._get_runtime_dir(), "active_care_policy.json"
            )
            if not scores:
                # 空数据时跳过写入，已有文件则删除
                if os.path.exists(score_file):
                    os.remove(score_file)
            else:
                await self._write_json_file(score_file, self._policy_scores)
            if is_debug_enabled("active_care"):
                logger.info("Active Care: 策略分值已保存到磁盘")

    async def update_policy_reward(self, action: str, reward: float) -> None:
        """增量更新 Bandit 策略分值（指数加权移动平均，EMA）

        闭环反馈：select_action_bandit 读取 → update_policy_reward 写入。
        原实现只有 select，没有 update，导致 bandit 永远从空分值选，
        退化为"完全随机 + LLM 兜底"。本方法接入后 bandit 才真正"学习"。

        更新公式：avg_new = avg_old + (reward - avg_old) / count
        （增量平均，等价于样本均值的在线更新）

        Args:
            action: 动作名（如 share_thought / bio_complaint / curious_question）
            reward: 奖励值，正数（用户响应）/ 负数（用户忽略）

        注意：题材感知 MDP 上线后，bandit 仍保留用于"无题材上下文"的冷启动兜底，
        但主学习闭环已迁移到 update_mdp_reward（按 (state, action) 二维学习）。
        """
        from core.utils.error_handler import error_handling

        async with error_handling(default_return=None, log_level="warning"):
            scores = await self.load_policy_scores()
            entry = scores.get(action) or {"avg_reward": 0.0, "count": 0}
            count = int(entry.get("count", 0)) + 1
            avg_old = float(entry.get("avg_reward", 0.0))
            avg_new = avg_old + (float(reward) - avg_old) / count
            scores[action] = {
                "avg_reward": round(avg_new, 4),
                "count": count,
            }
            await self.save_policy_scores(scores)
            if is_debug_enabled("active_care"):
                logger.info(
                    "Active Care: Bandit reward 更新 action=%s reward=%.2f avg=%.4f count=%d",
                    action, reward, avg_new, count,
                )

    # ==================== 题材感知 MDP Q 表 ====================

    async def load_mdp_q(self) -> Dict[str, Any]:
        """从磁盘加载 MDP Q 表（键格式 "<state_key>::<action>"）。"""
        from core.utils.error_handler import error_handling

        async with error_handling(default_return={}, log_level="warning"):
            q_file = os.path.join(self._get_runtime_dir(), "active_care_mdp.json")
            if os.path.exists(q_file):
                async with aiofiles.open(q_file, "r", encoding="utf-8") as f:
                    content = await f.read()
                    if content.strip():
                        data = json.loads(content)
                        logger.info(
                            "Active Care: 已从磁盘加载 MDP Q 表 (%d 个状态-动作对)",
                            len(data),
                        )
                        return data
        return {}

    async def save_mdp_q(self, q: Dict[str, Any]) -> None:
        """将 MDP Q 表保存到磁盘。"""
        from core.utils.error_handler import error_handling

        async with error_handling(default_return=None, log_level="error"):
            self._mdp_q_cache = q
            q_file = os.path.join(self._get_runtime_dir(), "active_care_mdp.json")
            if not q:
                if os.path.exists(q_file):
                    os.remove(q_file)
            else:
                await self._write_json_file(q_file, q)
            if is_debug_enabled("active_care"):
                logger.info("Active Care: MDP Q 表已保存到磁盘 (%d 对)", len(q))

    async def _ensure_proactive_count_cache(self) -> Dict[str, Any]:
        if self._proactive_count_cache is not None:
            return self._proactive_count_cache
        pc_file = os.path.join(self._get_runtime_dir(), "proactive_count.json")
        self._proactive_count_cache = await self._read_json_file(pc_file)
        return self._proactive_count_cache

    async def get_proactive_count(self, date_key: str) -> int:
        pc = await self._ensure_proactive_count_cache()
        return int(pc.get(date_key) or 0)

    async def increment_proactive_count(self, date_key: str):
        pc = await self._ensure_proactive_count_cache()
        pc[date_key] = int(pc.get(date_key) or 0) + 1
        self._proactive_count_cache = pc
        pc_file = os.path.join(self._get_runtime_dir(), "proactive_count.json")
        await self._write_json_file(pc_file, pc)

    async def get_plan(self) -> Dict[str, Any]:
        plan_file = os.path.join(self._get_runtime_dir(), "proactive_plan.json")
        return await self._read_json_file(plan_file)

    async def save_plan(self, plan: Dict[str, Any]):
        plan_file = os.path.join(self._get_runtime_dir(), "proactive_plan.json")
        if not plan:
            # 空数据时跳过写入，已有文件则删除
            if os.path.exists(plan_file):
                os.remove(plan_file)
        else:
            await self._write_json_file(plan_file, plan)

    # ==================== 用户画像存储（独立于 proactive_state） ====================

    _user_profile_cache: Dict[str, Dict[str, Any]] = {}

    async def get_user_profile(self, scope: Optional[str] = None) -> Dict[str, Any]:
        """获取用户画像数据（独立于 proactive_state）

        Args:
            scope: 可选的 scope。传入时直接读取对应 scope 的文件。

        Returns:
            用户画像字典
        """
        cache_key = scope or self._runtime_scope
        if cache_key in self._user_profile_cache:
            return self._user_profile_cache[cache_key]

        profile_file = os.path.join(self._get_runtime_dir(scope), "user_profile.json")
        if os.path.exists(profile_file):
            try:
                profile = await self._read_json_file(profile_file)
            except Exception:
                profile = {}
        else:
            profile = {}

        self._user_profile_cache[cache_key] = profile
        return profile

    async def save_user_profile(self, updates: Dict[str, Any], scope: Optional[str] = None) -> Dict[str, Any]:
        """保存用户画像数据（独立于 proactive_state）

        Args:
            updates: 要更新的键值对
            scope: 可选的 scope。传入时不使用实例缓存，直接读取-合并-写入对应 scope 的文件。

        Returns:
            更新后的完整画像
        """
        cache_key = scope or self._runtime_scope

        # 读取当前画像
        profile = await self.get_user_profile(scope=scope)

        # 合并更新
        profile.update(updates)

        # 写入文件
        profile_file = os.path.join(self._get_runtime_dir(scope), "user_profile.json")
        if not profile:
            # 空数据时跳过写入，已有文件则删除
            if os.path.exists(profile_file):
                os.remove(profile_file)
        else:
            await self._write_json_file(profile_file, profile)

        # 更新缓存
        self._user_profile_cache[cache_key] = profile
        return profile

    def invalidate_user_profile_cache(self, scope: Optional[str] = None):
        """使用户画像缓存失效

        Args:
            scope: 可选的 scope。不传则清除所有缓存。
        """
        if scope:
            self._user_profile_cache.pop(scope, None)
        else:
            self._user_profile_cache.clear()
