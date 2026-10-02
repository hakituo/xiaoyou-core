"""主动关怀 Prompt 上下文构建器

从 prompt_builder.py 拆分而来，包含所有纯数据拉取/格式化逻辑：
- 特殊事件注入
- 设备上下文构建
- 生物/饮食/学习上下文构建
- 健康提醒构建
- 人设主动关怀风格加载
"""

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.utils.common import get_project_root
from core.character.managers.persona_manager import get_persona_manager
from core.services.life_simulation.service import get_life_simulation_service
from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    TONE_REFERENCE_HEADER,
    DEVICE_CONTEXT_MOBILE_TEMPLATE,
    DEVICE_CONTEXT_QQ,
    DEVICE_CONTEXT_WEB,
)


# ── 模块级缓存 ──────────────────────────────────────────────
_bio_food_cache: Dict[str, Any] = {"bio_ts": 0.0, "bio": "", "food_ts": 0.0, "food": ""}
_BIO_FOOD_CACHE_TTL: float = 30.0

_persona_cfg_cache: Dict[str, Any] = {}
_persona_cfg_cache_ts: float = 0.0
_PERSONA_CFG_CACHE_TTL: float = 60.0

_ROLE_PROMPT_CONFIG_ROOT = Path(get_project_root()) / "core" / "character" / "configs"
_role_prompt_cache: Dict[str, Dict[str, Any]] = {}


# ── 上下文构建函数 ──────────────────────────────────────────

def _load_special_events_injection() -> str:
    try:
        path = os.path.join(
            get_project_root(), "core", "character", "special_events.json"
        )
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        events = data.get("events", [])
        reflexes = data.get("reflexes", {})
        lines = [TONE_REFERENCE_HEADER]
        if events:
            lines.append("- 记忆语气示例:")
            sample_events = random.sample(events, min(3, len(events)))
            for e in sample_events:
                content = e.get("content", "")
                emo = e.get("emotion", "")
                if content:
                    lines.append(f"  * \"{content}\" ({emo})")
        if reflexes:
            lines.append("- 本能反应示例:")
            for key in ["high_cpu", "low_battery", "late_night"]:
                opts = reflexes.get(key, [])
                if opts:
                    lines.append(f"  * [{key}]: \"{random.choice(opts)}\"")
        return "\n".join(lines) + "\n"
    except Exception:
        return ""


def _build_device_context_text(
    now: float, device_context: Optional[Dict[str, Any]], client_type: Optional[str]
) -> Tuple[str, bool]:
    txt = ""
    is_mobile = client_type in ["native", "websocket"]
    has_fresh_mobile_data = False
    ctx = device_context or {}
    ts = ctx.get("timestamp")
    if ts:
        try:
            has_fresh_mobile_data = (now - float(ts)) < 3600
        except Exception:
            has_fresh_mobile_data = False
    if has_fresh_mobile_data:
        try:
            parts = []
            batt = ctx.get("battery_level")
            charging = ctx.get("is_charging")
            if batt is not None:
                b_pct = int(float(batt) * 100)
                c_status = "充电中" if charging else "未充电"
                parts.append(f"电量{b_pct}%({c_status})")
            net = ctx.get("network_type")
            if net:
                parts.append(f"网络:{net}")
            app = ctx.get("current_app")
            if app:
                parts.append(f"前台APP:{app}")
            loc = ctx.get("location")
            if loc and isinstance(loc, dict) and loc.get("label"):
                parts.append(f"位置:{loc.get('label')}")
            if parts:
                txt = DEVICE_CONTEXT_MOBILE_TEMPLATE.format(status_parts=", ".join(parts))
        except Exception:
            pass
    elif client_type == "qq":
        txt = DEVICE_CONTEXT_QQ
    elif client_type == "web":
        txt = DEVICE_CONTEXT_WEB
    return txt, is_mobile


def extract_known_sleep_time_fact(summary_text: str) -> str:
    from core.agents.chat_agent_components.persona_system.prompt.components import _extract_known_sleep_time_fact
    return _extract_known_sleep_time_fact(summary_text)


def _build_bio_context_text(user_id: Optional[str]) -> str:
    now = time.time()
    if (now - _bio_food_cache["bio_ts"]) < _BIO_FOOD_CACHE_TTL and _bio_food_cache["bio"]:
        return _bio_food_cache["bio"]
    from core.agents.chat_agent_components.persona_system.prompt.components import build_bio_context_for_active_care
    result = build_bio_context_for_active_care(user_id)
    _bio_food_cache["bio"] = result
    _bio_food_cache["bio_ts"] = now
    return result


def _build_health_reminder_prompt(sys_prompt_type: str) -> str:
    """有依据的健康提醒（Prompt v2）。

    2026-09-04：移除"随机塞一句喝水/站起来活动"的通用健康泛提示——
    没有真实健康信号就不提醒（v2 原则：没有健康数据就不要生成喝水提醒）。
    真正有可靠生理/健康信号的健康提醒由 user_health_reminder 等硬事件路径触发。
    """
    return ""


def _build_food_context_text() -> str:
    now = time.time()
    if (now - _bio_food_cache["food_ts"]) < _BIO_FOOD_CACHE_TTL and _bio_food_cache["food"]:
        return _bio_food_cache["food"]
    from core.agents.chat_agent_components.persona_system.prompt import build_food_context_text as _build_food
    try:
        sim_service = get_life_simulation_service()
        st = sim_service.get_state() if sim_service else {}
        life_stats = st.get("life", {}) if isinstance(st, dict) else {}
        result = _build_food(life_stats)
    except Exception:
        result = ""
    _bio_food_cache["food"] = result
    _bio_food_cache["food_ts"] = now
    return result


def build_role_activity_context_text(persona_filename: str, *, current_facts: dict | None = None) -> str:
    """按自主角色 scope 只读当前计划和已有实例，复用主聊天事实投影。"""
    from core.character.runtime_roles import is_autonomous_role
    from core.utils.data.scope_registry import resolve_persona_slug_scope
    from core.agents.chat_agent_components.persona_system.prompt.components.character_daily_context import (
        build_character_daily_context,
    )

    scope = resolve_persona_slug_scope(persona_filename)
    if not scope or not is_autonomous_role(scope):
        return ""
    if current_facts is not None:
        return build_character_daily_context(persona_filename, current_facts=current_facts)
    return build_character_daily_context(persona_filename)


def build_role_sleep_context_text(persona_name: str = "", persona_filename: str = "") -> str:
    """构建角色睡眠状态上下文。"""
    try:
        from core.services.character_daily.engine import get_character_daily_engine
        from core.services.life_simulation import get_life_simulation_service

        lowered_filename = str(persona_filename or "").lower()
        lowered_name = str(persona_name or "").lower()
        role_id = "ling" if "ling" in lowered_filename or "Ling" in persona_name or "ling" in lowered_name else "aveline"

        life_sim = get_life_simulation_service()
        sleep_summary = life_sim.get_sleep_summary(role_id) if life_sim else {}
        if not sleep_summary:
            return ""

        lines = []
        phase = str(sleep_summary.get("phase") or "")
        if phase:
            lines.append(f"角色当前睡眠状态：{phase}")
        impact = str(sleep_summary.get("impact_level") or "none")
        if impact != "none":
            lines.append(f"今日睡眠影响等级：{impact}")
        if float(sleep_summary.get("sleep_debt_hours", 0.0) or 0.0) >= 0.3:
            lines.append(
                f"睡眠债约 {float(sleep_summary.get('sleep_debt_hours', 0.0) or 0.0):.1f} 小时"
            )
        if str(sleep_summary.get("nightmare_level") or "none") != "none":
            lines.append(f"昨夜有睡眠质量波动：{sleep_summary.get('nightmare_level')}")

        engine = get_character_daily_engine()
        if engine:
            wakeup_context = engine.build_wakeup_recovery_context(role_id)
            if wakeup_context:
                lines.append(wakeup_context.replace("\n", "；"))

        if not lines:
            return ""
        return "角色侧状态：" + "；".join(lines)
    except Exception:
        return ""


def _build_study_context_text() -> str:
    from core.agents.chat_agent_components.persona_system.prompt.components import build_study_context_for_active_care
    return build_study_context_for_active_care()


def _load_active_care_persona_cfg(
    persona_filename: str = "",
    persona_name: str = "",
) -> Dict[str, Any]:
    global _persona_cfg_cache, _persona_cfg_cache_ts
    cache_key = f"{persona_filename}:{persona_name}"
    now = time.time()
    if cache_key in _persona_cfg_cache and (now - _persona_cfg_cache_ts) < _PERSONA_CFG_CACHE_TTL:
        return _persona_cfg_cache[cache_key]
    try:
        pm = get_persona_manager()
        cfg: Dict[str, Any] = {}
        if persona_filename:
            cfg = pm.get_persona_by_filename(persona_filename) or {}
        if not cfg:
            current_filename = str(pm.get_current_filename() or "").strip()
            current_cfg = pm.get_current_persona() or {}
            if persona_filename and current_filename and persona_filename == current_filename:
                cfg = current_cfg if isinstance(current_cfg, dict) else {}
        if not cfg and persona_name:
            for item in pm.list_personas():
                filename = str((item or {}).get("filename") or "").strip()
                if not filename:
                    continue
                item_cfg = pm.get_persona_by_filename(filename) or {}
                identity = item_cfg.get("identity") if isinstance(item_cfg, dict) else {}
                cn_name = str((identity or {}).get("cn_name") or "").strip()
                name = str((identity or {}).get("name") or "").strip()
                if persona_name in {cn_name, name}:
                    result = item_cfg if isinstance(item_cfg, dict) else {}
                    _persona_cfg_cache[cache_key] = result
                    _persona_cfg_cache_ts = now
                    return result
        result = cfg if isinstance(cfg, dict) else {}
        _persona_cfg_cache[cache_key] = result
        _persona_cfg_cache_ts = now
        return result
    except Exception:
        return {}


def _build_persona_active_care_style(
    persona_prompt: str,
    persona_filename: str = "",
    persona_name: str = "",
) -> str:
    cfg = _load_active_care_persona_cfg(persona_filename, persona_name)
    profile = _get_role_active_care_profile(cfg)
    guidelines = cfg.get("active_care_guidelines", []) if isinstance(cfg, dict) else []
    normalized = (
        [str(x).strip() for x in guidelines if str(x).strip()]
        if isinstance(guidelines, list)
        else []
    )
    profile_guidelines = profile.get("guidelines") if isinstance(profile, dict) else []
    if isinstance(profile_guidelines, list):
        normalized.extend(
            str(item).strip() for item in profile_guidelines if str(item).strip()
        )
    return "\n".join(dict.fromkeys(normalized))


def _load_role_prompt_file(relative_path: str) -> Dict[str, Any]:
    """读取角色自己声明的 Prompt 文件，并在文件变更后刷新缓存。"""
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized:
        return {}
    path = (_ROLE_PROMPT_CONFIG_ROOT / normalized).resolve()
    try:
        path.relative_to(_ROLE_PROMPT_CONFIG_ROOT.resolve())
        mtime_ns = path.stat().st_mtime_ns
        cache_key = str(path)
        cached = _role_prompt_cache.get(cache_key) or {}
        if cached.get("mtime_ns") == mtime_ns:
            data = cached.get("data")
            return data if isinstance(data, dict) else {}
        data = json.loads(path.read_text(encoding="utf-8"))
        result = data if isinstance(data, dict) else {}
        _role_prompt_cache[cache_key] = {"mtime_ns": mtime_ns, "data": result}
        return result
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _get_role_active_care_profile(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """从角色自己的 Prompt 配置读取 Active Care 规则与示例。

    普通角色可直接把 ``active_care`` 放在主角色文件中。分层 Persona 可在
    ``meta.active_care_prompt_file`` 声明所属 Prompt 文件，例如Ye的
    ``ye/voice_ye.json``；这样示例仍由角色自己持有，不再维护中央角色表。
    """
    if not isinstance(cfg, dict):
        return {}
    profile = cfg.get("active_care")
    meta = cfg.get("meta")
    prompt_file = (
        str(meta.get("active_care_prompt_file") or "").strip()
        if isinstance(meta, dict)
        else ""
    )
    if prompt_file:
        role_document = _load_role_prompt_file(prompt_file)
        owned_profile = role_document.get("active_care")
        if isinstance(owned_profile, dict):
            return owned_profile
    return profile if isinstance(profile, dict) else {}


def _build_persona_active_care_examples(
    sys_prompt_type: str,
    persona_filename: str = "",
    persona_name: str = "",
) -> str:
    """构建当前角色、当前任务的少样本引导，不把其他任务样本全量灌入。"""
    cfg = _load_active_care_persona_cfg(persona_filename, persona_name)
    profile = _get_role_active_care_profile(cfg)
    examples_by_type = profile.get("examples") if isinstance(profile, dict) else {}
    examples = (
        examples_by_type.get(str(sys_prompt_type or "").strip())
        if isinstance(examples_by_type, dict)
        else None
    )
    if not isinstance(examples, list):
        return ""

    lines = [
        "\n【P6：当前角色的 Active Care 示例】",
        "只学习关系动作、语气和节奏；仅在示例情境与当前可靠事实一致时使用，不照抄。",
    ]
    for item in examples[:4]:
        if isinstance(item, str):
            text = item.strip()
            if text:
                lines.append(f"- {text}")
            continue
        if not isinstance(item, dict):
            continue
        situation = str(item.get("situation") or "").strip()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        prefix = f"{situation}：" if situation else ""
        lines.append(f"- {prefix}{text}")
    return "\n".join(lines) + "\n" if len(lines) > 2 else ""


# ── 今日学习生活计划注入 ──────────────────────────────────────
_today_plan_cache: Dict[str, Any] = {"date": "", "text": "", "ts": 0.0}
_TODAY_PLAN_CACHE_TTL: float = 60.0  # 60 秒缓存，平衡时效性和性能


def _build_today_plan_text() -> str:
    """读取今日学习生活计划并格式化为注入 Active Care prompt 的文本

    同步读盘 + 60s 缓存。如果今日无计划返回空字符串。
    """
    import json as _json
    from core.utils.data_paths import get_user_data_dir as _get_user_data_dir
    from core.utils.time_utils import get_current_time as _get_current_time

    now = _get_current_time()
    date_str = now.strftime("%Y-%m-%d")
    now_ts = now.timestamp()

    # 命中缓存
    if (
        _today_plan_cache["date"] == date_str
        and _today_plan_cache["text"]
        and (now_ts - _today_plan_cache["ts"]) < _TODAY_PLAN_CACHE_TTL
    ):
        return _today_plan_cache["text"]

    text = ""
    try:
        plan_path = (
            _get_user_data_dir()
            / "daily"
            / now.strftime("%Y")
            / now.strftime("%m")
            / now.strftime("%d")
            / "plan.json"
        )
        if not plan_path.exists():
            _today_plan_cache.update({"date": date_str, "text": "", "ts": now_ts})
            return ""

        raw = plan_path.read_text(encoding="utf-8")
        if not raw.strip():
            _today_plan_cache.update({"date": date_str, "text": "", "ts": now_ts})
            return ""

        data = _json.loads(raw)
        items = data.get("items") or []
        if not items:
            _today_plan_cache.update({"date": date_str, "text": "", "ts": now_ts})
            return ""

        # 复用 JournalService.format_plan_for_injection 保持格式一致
        try:
            from core.services.journal.models import DailyPlan
            plan = DailyPlan.model_validate(data)
            from core.services.journal.service import get_journal_service
            text = get_journal_service().format_plan_for_injection(plan)
        except Exception:
            # fallback：简单格式化
            lines = [f"📅 {date_str} 计划："]
            for it in items:
                t = it.get("time") or "灵活"
                title = it.get("title") or "未命名"
                status = it.get("status", "pending")
                icon = {"pending": "⏳", "in_progress": "🔄", "completed": "✅", "skipped": "⏭️"}.get(status, "⏳")
                lines.append(f"  {icon} [{t}] {title}")
            text = "\n".join(lines)
    except Exception:
        text = ""

    _today_plan_cache.update({"date": date_str, "text": text, "ts": now_ts})
    return text


def build_deferred_reminders_text(proactive_state: Dict[str, Any]) -> str:
    """检查 proactive_state 中是否有推迟的计划提醒，格式化为注入文本。

    根据睡眠状态判断用户情况：
    - 有起床时间 → 用户已醒，中性描述
    - 无起床时间 + 距睡觉>8h → 可能在睡觉或未识别到起床
    - 无起床时间 + <8h → 不确定，中性描述
    """
    deferred = proactive_state.get("deferred_plan_reminders") or []
    if not deferred or not isinstance(deferred, list):
        return ""

    # 仅在用户清醒时注入（reduced_mode 非睡眠状态）
    reduced_mode_active = bool(proactive_state.get("reduced_mode_active"))
    reduced_mode_reason = str(proactive_state.get("reduced_mode_reason") or "none")
    if reduced_mode_active and reduced_mode_reason in ("goodnight", "sleep", "sleep_hint"):
        return ""  # 用户还在睡觉，不注入

    now_ts = time.time()
    max_age = 24 * 3600  # 24 小时过期

    # 判断用户是否可能在睡觉
    last_goodnight_ts = float(proactive_state.get("last_goodnight_ts") or 0)
    last_goodmorning_ts = float(proactive_state.get("last_goodmorning_ts") or 0)
    has_wakeup = last_goodmorning_ts > 0 and last_goodmorning_ts >= last_goodnight_ts
    sleep_elapsed_hours = (now_ts - last_goodnight_ts) / 3600 if last_goodnight_ts > 0 else 0
    likely_sleeping = (not has_wakeup and last_goodnight_ts > 0 and sleep_elapsed_hours > 8)

    lines = []
    valid_items = []
    for item in deferred:
        if not isinstance(item, dict):
            continue
        task_title = str(item.get("task_title") or "").strip()
        item_type = str(item.get("type") or "start").strip().lower()
        deferred_ts = float(item.get("deferred_ts") or 0)
        if not task_title:
            continue
        # 过期检查
        if deferred_ts > 0 and (now_ts - deferred_ts) > max_age:
            continue
        valid_items.append(item)
        if item_type == "end":
            lines.append(f"  - 「{task_title}」的时间到了（未送达）")
        else:
            lines.append(f"  - 该开始「{task_title}」了（未送达）")

    if not lines:
        # 所有过期，清除列表
        return ""

    count = len(lines)
    if likely_sleeping:
        header = f"用户可能还在睡觉，有 {count} 项计划提醒未送达（距睡觉已过{int(sleep_elapsed_hours)}小时，无起床记录）："
    else:
        header = f"有 {count} 项计划提醒未按时送达："
    return header + "\n" + "\n".join(lines)
