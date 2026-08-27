"""数字健康服务 (Digital Wellbeing)

负责应用使用时长限额的管理与复盘:

- 存储每日应用限额 (按 target_date 落盘, 可被用户/LLM 工具覆盖)
- 读取当日应用实际使用时长 (来自 DataSyncWorker 上报、sync_context 落盘的 app_usage.jsonl)
- 判断某应用是否超限、返回超限应用列表 (供 Android 端本地强退 / active care 播报)
- 供 Nightly 复盘调用: 根据今日 usage 给出明日限额建议 (auto), 由调用方用 LLM 生成或走规则兜底

数据落盘位置: {user_data_dir}/digital_wellbeing/limits_{date}.json
单例: get_wellbeing_service()
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional

from core.utils.data_paths import get_user_data_dir
from core.utils.logger import get_module_logger
from core.utils.time_utils import get_current_time, now_iso

logger = get_module_logger("DIGITAL_WELLBEING", "digital_wellbeing.log")


# 默认规则兜底: 单应用单日超过该用量则建议明日限额为该值的 80%
_DEFAULT_SOFT_THRESHOLD_MS = 2 * 3600 * 1000  # 2 小时
# 超限强退的硬性上限倍率 (auto 模式下, 超过建议限额的该倍率才真正强退, 留缓冲)
_ENFORCE_GRACE_RATIO = 1.0  # 1.0 = 到限额即触发

# package_name 前缀 -> 是否纳入数字健康监控 (系统应用/自身默认排除在限额之外)。
# 用前缀匹配: 自身包名可能是 com.aveline.ai.debug 等变体, 精确匹配会漏掉。
_EXCLUDED_PREFIXES = (
    "com.aveline.ai",  # 自身
    "com.android.systemui",
    "com.android.launcher",
)

# 用户明确指定"不设时长限额"的应用 (prefix 匹配)。与系统/自身排除一样,
# 既不会参与 nightly 自动设限, 也不会被超限强退。
_USER_NO_LIMIT_PREFIXES = (
    "com.tencent.mobileqq",  # QQ (聊天工具, 用户要求不限额)
    "com.openai.chatgpt",    # ChatGPT (用户要求不限额)
)


def _is_excluded(pkg: str) -> bool:
    """判断应用是否应被排除在数字健康限额之外 (按前缀匹配)。"""
    return any(
        pkg.startswith(prefix)
        for prefix in (*_EXCLUDED_PREFIXES, *_USER_NO_LIMIT_PREFIXES)
    )


def _parse_last_used_time(lut: Any) -> Optional[Any]:
    """把 last_used_time 解析为时区感知的 UTC datetime, 失败返回 None。

    Android 端传来的是 Instant.toString(), 形如 "2026-08-14T12:34:56.789Z"。
    Python 3.10 及以下的 datetime.fromisoformat 不支持 Z 后缀, 需先替换为 +00:00。
    """
    if not lut:
        return None
    from datetime import datetime, timezone

    try:
        if isinstance(lut, str):
            # 兼容 ISO-8601 的 Z 后缀
            dt = datetime.fromisoformat(lut.replace("Z", "+00:00"))
        elif isinstance(lut, datetime):
            dt = lut
        else:
            return None
        # 统一转 UTC 时区感知, 避免 naive/aware 相减报错
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


class DigitalWellbeingService:
    """应用使用时长限额服务 (进程内单例)。"""

    def __init__(self, base_dir: Optional[Any] = None) -> None:
        self._base_dir = (
            base_dir if base_dir is not None else (get_user_data_dir() / "digital_wellbeing")
        )
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # 进程内缓存: date -> limits dict (减少重复磁盘读)
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ── 限额存取 ──────────────────────────────────────────

    def _limits_path(self, target_date: str) -> Any:
        return self._base_dir / f"limits_{target_date}.json"

    def get_limits(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """读取某天的限额配置。

        Returns:
            {
              "date": "2026-08-09",
              "limits": {
                "com.douyin": {"limit_ms": 3600000, "app_name": "抖音", "source": "auto"}
              },
              "updated_at": "2026-08-08T23:10:00"
            }
        """
        if target_date is None:
            target_date = get_current_time().strftime("%Y-%m-%d")
        with self._lock:
            if target_date in self._cache:
                return self._cache[target_date]
            path = self._limits_path(target_date)
            if not path.exists():
                empty = {"date": target_date, "limits": {}, "updated_at": None}
                self._cache[target_date] = empty
                return empty
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data.setdefault("date", target_date)
                data.setdefault("limits", {})
                self._cache[target_date] = data
                return data
            except Exception as e:
                logger.warning(f"读取限额配置失败 {path}: {e}")
                empty = {"date": target_date, "limits": {}, "updated_at": None}
                self._cache[target_date] = empty
                return empty

    def save_limits(
        self,
        limits: Dict[str, Dict[str, Any]],
        target_date: Optional[str] = None,
        source: str = "user",
    ) -> Dict[str, Any]:
        """覆盖式保存某天的限额配置。

        Args:
            limits: {package_name: {"limit_ms": int, "app_name": str}} 或已含 source 字段
            target_date: 目标日期 (默认明天)
            source: 来源标记 (auto=nightly自动, user=用户/LLM手动)
        """
        if target_date is None:
            # 默认存到"明天": nightly 在凌晨运行时定的是用户醒来后要过的那天
            t = get_current_time()
            t = t.replace(day=t.day + 1) if t.day < 28 else t  # 简化: 月末由调用方传准
            target_date = t.strftime("%Y-%m-%d")
        with self._lock:
            data = self.get_limits(target_date)
            normalized: Dict[str, Any] = {}
            for pkg, val in limits.items():
                if not pkg or not isinstance(val, dict):
                    continue
                limit_ms = int(val.get("limit_ms", 0) or 0)
                if limit_ms <= 0:
                    continue
                item = {
                    "limit_ms": limit_ms,
                    "app_name": str(val.get("app_name") or pkg),
                    "source": str(val.get("source") or source),
                }
                sc = val.get("session_cap_ms")
                if sc:
                    item["session_cap_ms"] = int(sc)
                normalized[pkg] = item
            data["limits"] = normalized
            data["updated_at"] = now_iso()
            path = self._limits_path(target_date)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._cache[target_date] = data
            logger.info(
                "数字健康: 已保存 %s 限额 (%d 个应用, source=%s)",
                target_date,
                len(normalized),
                source,
            )
            return data

    def set_single_limit(
        self,
        package_name: str,
        limit_ms: int,
        app_name: Optional[str] = None,
        target_date: Optional[str] = None,
        source: str = "user",
    ) -> Dict[str, Any]:
        """设置/覆盖单个应用的限额 (供 set_app_limit 工具调用)。"""
        if target_date is None:
            t = get_current_time()
            t = t.replace(day=t.day + 1) if t.day < 28 else t
            target_date = t.strftime("%Y-%m-%d")
        with self._lock:
            data = self.get_limits(target_date)
            if limit_ms <= 0:
                # 0 或负数 = 移除限额
                data["limits"].pop(package_name, None)
            else:
                entry = data["limits"].get(package_name, {})
                new_entry = {
                    "limit_ms": limit_ms,
                    "app_name": app_name or package_name,
                    "source": source,
                }
                # 覆盖每日限额时保留已有的会话 cap, 避免互相覆盖丢失
                if entry.get("session_cap_ms"):
                    new_entry["session_cap_ms"] = entry["session_cap_ms"]
                data["limits"][package_name] = new_entry
            data["updated_at"] = now_iso()
            path = self._limits_path(target_date)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._cache[target_date] = data
            return data

    def set_session_cap(
        self,
        package_name: str,
        session_cap_ms: int,
        app_name: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """设置/清除单个应用的"会话限额"(一次性 cap)。

        会话限额与每日限额并用同一份当日用量, 消耗的时长同样计入每日总量:
        - 设置了会话 cap 后, 从生效时刻起该应用累计只能用 session_cap_ms,
          超限即强退, 直到调用方清除 (用户说"恢复/歇够了")。
        - session_cap_ms <= 0 表示清除会话 cap, 回到仅按每日限额判断。
        - 若该应用没有每日限额, 会话 cap 本身也足以触发强退。
        """
        if target_date is None:
            t = get_current_time()
            t = t.replace(day=t.day + 1) if t.day < 28 else t
            target_date = t.strftime("%Y-%m-%d")
        with self._lock:
            data = self.get_limits(target_date)
            entry = data["limits"].get(package_name)
            if session_cap_ms and session_cap_ms > 0:
                if entry is None:
                    data["limits"][package_name] = {
                        "limit_ms": 0,  # 无每日限额, 仅会话 cap
                        "app_name": app_name or package_name,
                        "source": "user",
                        "session_cap_ms": int(session_cap_ms),
                    }
                else:
                    entry["session_cap_ms"] = int(session_cap_ms)
            else:
                # 清除会话 cap
                if entry is not None:
                    entry.pop("session_cap_ms", None)
                    # 既无每日限额也无会话 cap 时, 移除整条配置
                    if not entry.get("limit_ms") and not entry.get(
                        "session_cap_ms"
                    ):
                        data["limits"].pop(package_name, None)
            data["updated_at"] = now_iso()
            path = self._limits_path(target_date)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._cache[target_date] = data
            logger.info(
                "数字健康: 已%s %s 会话限额 (target=%s)",
                "设置" if session_cap_ms and session_cap_ms > 0 else "清除",
                package_name,
                target_date,
            )
            return data

    # ── 用量读取与超限判断 ────────────────────────────────

    def get_today_usage(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """读取当日应用实际使用时长 (聚合自 app_usage.jsonl)。"""
        from routers.v1.context_device import read_today_app_usage

        return read_today_app_usage(target_date)

    def get_exceeded_apps(
        self,
        target_date: Optional[str] = None,
        usage: Optional[List[Dict[str, Any]]] = None,
        grace_ratio: float = _ENFORCE_GRACE_RATIO,
    ) -> List[Dict[str, Any]]:
        """返回已超限的应用列表。

        Args:
            target_date: 限额所属日期 (默认今天)
            usage: 外部传入的用量 (否则内部读取今日)
            grace_ratio: 宽容倍率, 实际用量 > limit_ms * grace_ratio 才算超限

        Returns:
            [{package_name, app_name, limit_ms, usage_ms, ratio}]
        """
        if target_date is None:
            target_date = get_current_time().strftime("%Y-%m-%d")
        limits_data = self.get_limits(target_date)
        limits = limits_data.get("limits", {})
        if not limits:
            return []
        if usage is None:
            usage = self.get_today_usage(target_date)

        exceeded: List[Dict[str, Any]] = []
        usage_by_pkg = {u["package_name"]: u for u in usage}
        for pkg, cfg in limits.items():
            u = usage_by_pkg.get(pkg)
            if not u:
                continue
            if _is_excluded(pkg):
                continue
            limit_ms = int(cfg.get("limit_ms", 0) or 0)
            if limit_ms <= 0:
                continue
            usage_ms = int(u.get("usage_time_ms", 0) or 0)
            if usage_ms > limit_ms * grace_ratio:
                exceeded.append(
                    {
                        "package_name": pkg,
                        "app_name": cfg.get("app_name") or u.get("app_name") or pkg,
                        "limit_ms": limit_ms,
                        "usage_ms": usage_ms,
                        "ratio": round(usage_ms / limit_ms, 2) if limit_ms else 0,
                        # 修复: 必须把 last_used_time 透传出去, 否则下游
                        # maybe_notify_exceeded_via_active_care 的 recent_active
                        # 检查取不到该字段, 永远跳过, 导致用户早已不在用该应用
                        # 时仍发虚假的"超限关怀"消息。
                        "last_used_time": u.get("last_used_time"),
                    }
                )
        exceeded.sort(key=lambda x: x["ratio"], reverse=True)
        return exceeded

    # ── Nightly 复盘: 生成明日限额建议 ────────────────────

    def build_limit_suggestion(
        self,
        today_date: Optional[str] = None,
        usage: Optional[List[Dict[str, Any]]] = None,
        max_apps: int = 10,
    ) -> Dict[str, Dict[str, Any]]:
        """基于今日用量给出明日限额建议 (规则兜底, 不依赖 LLM)。

        规则:
        - 仅对今日用量超过软阈值 (_DEFAULT_SOFT_THRESHOLD_MS) 的 Top N 应用设限额
        - 限额 = 今日用量的 80% (向下取整到 15 分钟), 且不高于今日用量
        - 系统应用/自身排除

        若调用方希望用 LLM 生成更智能的限额, 可先用本函数拿基线再让 LLM 调整。
        """
        if today_date is None:
            today_date = get_current_time().strftime("%Y-%m-%d")
        if usage is None:
            usage = self.get_today_usage(today_date)

        suggestions: Dict[str, Dict[str, Any]] = {}
        for u in usage:
            pkg = u.get("package_name")
            if not pkg or _is_excluded(pkg):
                continue
            ms = int(u.get("usage_time_ms", 0) or 0)
            if ms < _DEFAULT_SOFT_THRESHOLD_MS:
                continue
            # 80% 向下取整到 15 分钟
            step = 15 * 60 * 1000
            suggested = int((ms * 0.8) // step) * step
            suggested = max(suggested, step)  # 至少 15 分钟
            suggestions[pkg] = {
                "limit_ms": suggested,
                "app_name": u.get("app_name") or pkg,
                "source": "auto",
            }
            if len(suggestions) >= max_apps:
                break
        return suggestions

    # 主动关怀冷却: 同一应用超限后多久内不再重复发消息 (避免每 15 分钟刷屏)
    _CARE_COOLDOWN_SECONDS = 6 * 3600
    _last_care_ts: Dict[str, float] = {}
    # 最近活跃窗口: 应用 last_used_time 超过此时间的不再触发关怀 (用户早已没在用)
    _RECENT_ACTIVE_MINUTES = 30

    async def maybe_notify_exceeded_via_active_care(
        self,
        target_date: Optional[str] = None,
        usage: Optional[List[Dict[str, Any]]] = None,
        recent_active_minutes: int = _RECENT_ACTIVE_MINUTES,
    ) -> List[str]:
        """检查今日超限应用, 通过 Active Care 给 Master 发关怀消息 (带冷却)。

        注意: 这是"通知"层。真正的强制退出由 Android 端本地 UsageLimitMonitor
        完成 (离线也能拦)。后端这里只负责在手机在线同步时补一条有人情味的提醒。

        修复:
        1. 增加 recent_active_minutes 检查, last_used_time 超过该时间的应用跳过关怀,
           避免"用户今天已经看过但早已不在用"时仍触发虚假关怀。
        2. get_exceeded_apps 现在会透传 last_used_time; 此处用 _parse_last_used_time
           稳健解析 (兼容 Z 后缀), 缺失/解析失败时保守跳过 (不发关怀), 因为无法
           确认用户最近是否还在用该应用。

        Returns:
            本次实际发送了关怀消息的应用 app_name 列表
        """
        import time
        from datetime import datetime, timezone

        exceeded = self.get_exceeded_apps(target_date=target_date, usage=usage)
        if not exceeded:
            return []

        now_ts = time.time()
        notified: List[str] = []
        for app in exceeded:
            pkg = app["package_name"]
            last = self._last_care_ts.get(pkg, 0.0)
            if now_ts - last < self._CARE_COOLDOWN_SECONDS:
                continue
            # 检查最近活跃: 只有用户"最近还在用这个应用"时才发关怀。
            # last_used_time 缺失或解析失败时, 保守跳过 (不发虚假关怀)。
            if recent_active_minutes > 0:
                lut_dt = _parse_last_used_time(app.get("last_used_time"))
                if lut_dt is None:
                    logger.info(
                        "数字健康: %s 超限但 last_used_time 缺失/解析失败, 跳过关怀",
                        app["app_name"],
                    )
                    continue
                age_sec = (datetime.now(timezone.utc) - lut_dt).total_seconds()
                if age_sec > recent_active_minutes * 60:
                    logger.info(
                        "数字健康: %s 超限但最后使用于 %ss 前, 跳过关怀",
                        app["app_name"], int(age_sec),
                    )
                    continue
            self._last_care_ts[pkg] = now_ts
            try:
                from core.services.active_care.core.service import (
                    get_active_care_service,
                )

                svc = get_active_care_service()
                if svc is None or svc.executor is None:
                    logger.warning("数字健康: Active Care 服务未初始化, 跳过关怀消息")
                    continue
                h = app["limit_ms"] // 3600_000
                m = (app["limit_ms"] % 3600_000) // 60_000
                limit_str = f"{h}h{m}m" if h else f"{m}m"
                uh = app["usage_ms"] // 3600_000
                um = (app["usage_ms"] % 3600_000) // 60_000
                usage_str = f"{uh}h{um}m" if uh else f"{um}m"
                user_input = (
                    f"用户的手机应用 {app['app_name']} 今日已使用 {usage_str}, "
                    f"超过了设定的每日限额 {limit_str}。"
                    f"请以 Aveline 的口吻自然地关心一下用户，简短提醒他休息一下眼睛或"
                    f"换个方式放松，不要说教。系统没有收到强制退出结果，禁止声称应用"
                    f"已经被关闭、被踢出或强制退出。"
                )
                ok = await svc.executor.trigger_message(
                    sys_prompt_type="usage_limit_exceeded",
                    user_input_mock=user_input,
                    specific_instruction=user_input,
                    client_type="qq",
                    persona_filename="qq/Aveline_QQ_Master.json",
                )
                if ok:
                    notified.append(app["app_name"])
                    logger.info("数字健康: 已发送超限关怀消息 -> %s", app["app_name"])
            except Exception as e:
                logger.warning(f"数字健康: 发送超限关怀消息失败 {app['app_name']}: {e}")
        return notified


_service: Optional["DigitalWellbeingService"] = None
_service_lock = threading.Lock()


def get_wellbeing_service() -> DigitalWellbeingService:
    """获取 DigitalWellbeingService 单例。"""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = DigitalWellbeingService()
    return _service
