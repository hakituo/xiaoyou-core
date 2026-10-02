"""ChatAgent 非流式 handler：BERT 生活状态记录（起床 / 用餐 / 饮水）。

从 ``core/agents/chat_agent_components/handler.py`` 拆出（原 1020 行单文件按职责拆为
薄壳门面 + 5 个职责子模块），本模块负责：
- 内部触发消息识别 ``_is_internal_trigger_message``
- 「我在吃/我在喝」自述识别 ``_is_meal_or_drink_self_report``
- BERT 意图分析驱动的状态记录 ``_record_status_via_bert``

⚠️ 模块级 patch 语义：测试会按名替换门面模块的 ``now_str`` / ``datetime``
（``monkeypatch.setattr(handler, "now_str", ...)``），因此这两个名字必须在**调用期**
从门面模块取名，不能顶层 from-import 固化。
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.agents.chat_agent_components import handler as _facade
from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


def _is_internal_trigger_message(text: str) -> bool:
    raw = str(text or "")
    upper = raw.upper()
    if "_TRIGGER]" in upper:
        return True
    if "[LAST_USER_MESSAGE]:" in upper:
        return True
    if "[ACTIVE_CARE_CONTEXT_CONTINUATION]" in upper:
        return True
    # 注：这里原先还有一层 `if "[NOTIFICATION_TRIGGER]" in upper: return True`，
    # 但该字面量本身以 `_TRIGGER]` 结尾，上面第 58 行的 `"_TRIGGER]"` 判断必然先命中，
    # 故那一层恒不执行（2026-09-23 删除，可观察行为零变化）。
    # 通知触发消息仍由 `_TRIGGER]` 分支覆盖。
    if "[SYSTEM EVENT]" in upper:
        return True
    return False


def _is_meal_or_drink_self_report(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if _is_internal_trigger_message(raw):
        return False
    lower = raw.lower()
    if "？" in raw or "?" in raw:
        return False
    zh_pattern = re.search(
        r"(我(刚|才|已经|都)?|今天我|刚刚).{0,8}(喝|吃|饮|进食)",
        raw,
    )
    if zh_pattern:
        return True
    en_pattern = re.search(
        r"\b(i|i'm|i am|i've|i just|i already)\b.{0,24}\b(ate|eat|drank|drink|drinking)\b",
        lower,
    )
    if en_pattern:
        return True
    return False


def _record_status_via_bert(
    message: str,
    system_prompt_override: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """按 BERT 意图记录起床 / 用餐 / 饮水状态。

    返回 ``(is_trivial_record, system_prompt_override)``：
    - ``is_trivial_record`` 为 True 时调用方应跳过长期记忆存储；
    - ``system_prompt_override`` 可能被追加了给 LLM 的系统提示（原变量语义）。
    """
    is_trivial_record = False
    try:
        internal_trigger_message = _is_internal_trigger_message(message)
        from core.services.data_ops.bert_analyzer import get_bert_analyzer
        from core.services.workspace.status_manager import get_user_status_manager

        analyzer = get_bert_analyzer()
        # We only care about specific intents here
        candidates = ["RECORD_WAKEUP", "RECORD_MEAL", "RECORD_DRINK"]
        analysis = analyzer.analyze_intent(message, candidates=candidates)

        intent = analysis.get("intent")
        # Increase confidence threshold to avoid false positives for trivial chat
        # "今天天气不错" might trigger some intent with low confidence
        confidence = analysis.get("confidence", 0.0)

        # Require higher confidence for skipping memory
        # Also check for "Wakeup" specific keywords to avoid false positive like "今天天气不错"
        if internal_trigger_message:
            logger.info("Skipped BERT status record for internal trigger message.")
        elif intent == "RECORD_WAKEUP" and confidence > 0.7:
            is_wakeup = any(k in message for k in ["醒", "起", "早安"])
            if not is_wakeup:
                # BERT false positive
                logger.info(f"Ignored BERT Wakeup false positive: {message} (conf={confidence:.2f})")
            else:
                # Record Wakeup
                manager = get_user_status_manager()
                time_str = _facade.now_str("%H:%M")
                manager.add_status("今日起床", f"时间: {time_str}", duration_days=1)
                logger.info(f"Recorded Wakeup via BERT: {time_str}")

                # Add a system hint so LLM knows
                from core.agents.chat_agent_components.persona_system.prompt.service_prompts import HANDLER_WAKE_UP_NOTIFICATION
                system_prompt_override = (system_prompt_override or "") + HANDLER_WAKE_UP_NOTIFICATION.format(time_str=time_str)
                is_trivial_record = True

        elif intent == "RECORD_MEAL" and confidence > 0.7:
            if not _is_meal_or_drink_self_report(message):
                logger.info(
                    "Ignored BERT meal intent: message is not explicit self-report."
                )
                intent = "NONE"
            else:
            # Record Meal
                manager = get_user_status_manager()
                time_str = _facade.now_str("%H:%M")

                food = message
                remove_kws = [
                    "吃饭", "吃了", "吃过", "吃点", "吃", "喝了", "喝点", "喝",
                    "早饭", "早餐", "午饭", "午餐", "晚饭", "晚餐", "夜宵", "宵夜",
                    "东西", "饿了", "饱了", "正在", "在", "下午茶", "点心", "零食",
                    "我", "你", "啊", "了", "的", "呢", "吧", "嘛", "哦", "嗯"
                ]
                for kw in remove_kws:
                     food = food.replace(kw, "")
                food = food.strip()

                if not food or len(food) < 2:
                    m = re.search(r"(?:吃|喝)(?:了|点|过)?([^，。！？,\n]+)", message)
                    if m:
                        food = m.group(1).strip()
                    else:
                        food = "未说明具体食物"

                meal_name = "用餐记录"
                hour = _facade.datetime.now().hour

                is_snack = any(k in message for k in ["零食", "点心", "下午茶", "蛋糕", "饼干", "薯片", "奶茶", "咖啡"])

                if is_snack:
                    meal_name = "零食/加餐"
                else:
                    if 5 <= hour < 10:
                        meal_name = "早餐"
                    elif 11 <= hour < 14:
                        meal_name = "午餐"
                    elif 17 <= hour < 21:
                        meal_name = "晚餐"
                    elif hour >= 21 or hour < 5:
                        meal_name = "夜宵"

                manager.add_status(meal_name, f"内容: {food} (时间: {time_str})", duration_days=1)
                logger.info(f"Recorded Meal via BERT: {meal_name} - {food}")

                try:
                    from core.services.daily.manager import get_daily_manager
                    daily_mgr = get_daily_manager()
                    daily_mgr.record_meal(meal_name, food)
                except Exception as e:
                    logger.warning(f"Failed to sync meal to daily record: {e}")

                from core.agents.chat_agent_components.persona_system.prompt.service_prompts import HANDLER_EAT_NOTIFICATION
                system_prompt_override = (system_prompt_override or "") + HANDLER_EAT_NOTIFICATION.format(food=food, meal_name=meal_name)
                is_trivial_record = True

        elif intent == "RECORD_DRINK" and confidence > 0.7:
            if not _is_meal_or_drink_self_report(message):
                logger.info(
                    "Ignored BERT drink intent: message is not explicit self-report."
                )
                intent = "NONE"
            else:
            # Record Drink
                manager = get_user_status_manager()
                time_str = _facade.now_str("%H:%M")

                amount = 200
                m = re.search(r"(\d+)(ml|毫升|升|L|杯|瓶|口)", message, re.IGNORECASE)
                if m:
                    val = int(m.group(1))
                    unit = m.group(2).lower()
                    if unit in ["升", "l"]:
                        val *= 1000
                    elif unit in ["杯", "瓶"]:
                        val *= 250
                    elif unit in ["口"]:
                        val = 50
                    amount = val

                statuses = manager._load_statuses()
                current_total = 0
                for s in statuses:
                    if s["name"] == "今日饮水":
                        m_exist = re.search(r"(\d+)ml", s["description"])
                        if m_exist:
                            current_total = int(m_exist.group(1))
                        break

                new_total = current_total + amount
                manager.add_status("今日饮水", f"已喝 {new_total}ml (最近: {time_str})", duration_days=1)

                try:
                    from core.services.daily.manager import get_daily_manager
                    daily_mgr = get_daily_manager()
                    daily_mgr.record_drink("drink", f"喝水 {amount}ml")
                except Exception as e:
                    logger.warning(f"Failed to sync drink to daily record: {e}")

                logger.info(f"Recorded Drink via BERT: {amount}ml (Total: {new_total}ml)")
                from core.agents.chat_agent_components.persona_system.prompt.service_prompts import HANDLER_DRINK_NOTIFICATION
                system_prompt_override = (system_prompt_override or "") + HANDLER_DRINK_NOTIFICATION.format(amount=amount, new_total=new_total)
                is_trivial_record = True

    except Exception as e:
        logger.error(f"Failed to record status via BERT: {e}")

    return is_trivial_record, system_prompt_override
