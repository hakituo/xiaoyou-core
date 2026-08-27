import asyncio
import re
from typing import Any

from core.utils.time_utils import get_current_time


def _sync_sleep_to_active_care(time_str: str, target_date: str = None):
    """同步更正后的睡觉时间到 Active Care 的 proactive_state（使用统一管理器）"""
    if not time_str:
        return
    try:
        from core.services.active_care.state import get_sleep_state_manager
        manager = get_sleep_state_manager()
        manager.sync_sleep_time_sync(time_str, target_date)
    except Exception as e:
        print(f"[correction] _sync_sleep_to_active_care failed: {e}")


def _sync_wakeup_to_active_care(time_str: str):
    """同步更正后的起床时间到 Active Care 的 proactive_state（使用统一管理器）"""
    if not time_str:
        return
    try:
        from core.services.active_care.state import get_sleep_state_manager
        manager = get_sleep_state_manager()
        manager.sync_wakeup_time_sync(time_str)
    except Exception as e:
        print(f"[correction] _sync_wakeup_to_active_care failed: {e}")


def has_correction_intent(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    return bool(
        re.search(
            r"(更正|纠正|改成|修正|写错|记错|不是|不对|应该是|改一下记录|更新为)",
            raw,
            re.IGNORECASE,
        )
    )


def extract_time_hhmm(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    is_pm = bool(re.search(r"(晚上|晚|夜里|夜间|夜晚|傍晚|深夜|半夜)", raw))
    is_am = bool(re.search(r"(早上|早晨|清晨|上午|凌晨)", raw))
    # 上下文推断：没有明确上下午关键词时，根据"睡/起"推断
    has_sleep_kw = any(k in raw for k in ["睡", "困", "晚安", "躺"])
    has_wakeup_kw = any(k in raw for k in ["起", "醒", "早安", "早上好"])
    m = re.search(r"([01]?\d|2[0-3])\s*[:：]\s*([0-5]?\d)", raw)
    if m:
        h = int(m.group(1))
        minute = int(m.group(2))
        if is_pm and h < 12:
            h += 12
        if is_am and h == 12:
            h = 0
        # 上下文推断：没有上下午关键词时，根据睡/起推断
        if not is_pm and not is_am:
            if has_sleep_kw and 6 <= h <= 12:
                # "6点睡"→凌晨6点（熬夜），"12点睡"→凌晨0点或中午12点
                # 如果是"中午/下午"等明确标识已由 is_pm 处理
                # 这里只处理"X点睡"且X在6-12之间的情况，通常指凌晨
                pass  # 保持原值，因为凌晨6-12点睡觉是合理的
            if has_wakeup_kw and 6 <= h <= 12:
                # "6点起/9点起"→早上，不需要+12
                pass
        return f"{h:02d}:{minute:02d}"
    m2 = re.search(
        r"([零一二三四五六七八九十两\d]{1,3})\s*点(?:\s*(半|[0-5]?\d)\s*分?)?", raw
    )
    if not m2:
        return ""
    h_raw = str(m2.group(1) or "").strip()
    minute_raw = str(m2.group(2) or "").strip()
    map_cn = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    h = 0
    if h_raw.isdigit():
        h = int(h_raw)
    elif h_raw == "十":
        h = 10
    elif "十" in h_raw:
        parts = h_raw.split("十")
        left = map_cn.get(parts[0], 1) if parts[0] else 1
        right = map_cn.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        h = left * 10 + right
    else:
        h = map_cn.get(h_raw, 0)
    if h < 0 or h > 23:
        return ""
    if is_pm and h < 12:
        h += 12
    if is_am and h == 12:
        h = 0
    # 上下文推断：中文"X点睡/起"的上下午推断
    if not is_pm and not is_am:
        if has_sleep_kw and 1 <= h <= 5:
            # "1点睡/2点睡/5点睡"→凌晨，保持原值
            pass
        if has_wakeup_kw and 1 <= h <= 5:
            # "1点起/2点起"→凌晨起床（夜猫子），保持原值
            pass
    if minute_raw == "半":
        minute = 30
    else:
        minute = int(minute_raw) if minute_raw.isdigit() else 0
    if minute < 0 or minute > 59:
        minute = 0
    return f"{h:02d}:{minute:02d}"


def _infer_meal_type(text: str) -> str:
    raw = str(text or "")
    if "早餐" in raw or "早饭" in raw:
        return "breakfast"
    if "午餐" in raw or "午饭" in raw:
        return "lunch"
    if "晚餐" in raw or "晚饭" in raw:
        return "dinner"
    return "meal"


def _extract_meal_content(text: str) -> str:
    raw = str(text or "").strip()
    m = re.search(r"(?:吃了|喝了)([^，。！？,\n]{1,18})", raw)
    if m:
        return str(m.group(1) or "").strip()
    return "已吃"


def _extract_all_times(text: str) -> list:
    """提取文本中所有的时间（支持 HH:MM 和中文格式）"""
    raw = str(text or "").strip()
    if not raw:
        return []
    times = []
    
    for m in re.finditer(r"([01]?\d|2[0-3])\s*[:：]\s*([0-5]?\d)", raw):
        h = int(m.group(1))
        minute = int(m.group(2))
        times.append(f"{h:02d}:{minute:02d}")
    
    cn_map = {
        "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    
    cn_pattern = r"([零一二三四五六七八九十两\d]{1,3})\s*点(?:\s*(半|[零一二三四五六七八九\d]{0,2})\s*分?)?"
    for m in re.finditer(cn_pattern, raw):
        h_raw = str(m.group(1) or "").strip()
        min_raw = str(m.group(2) or "").strip()
        
        if h_raw.isdigit():
            h = int(h_raw)
        elif h_raw == "十":
            h = 10
        elif "十" in h_raw:
            parts = h_raw.split("十")
            left = cn_map.get(parts[0], 1) if parts[0] else 1
            right = cn_map.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
            h = left * 10 + right
        else:
            h = cn_map.get(h_raw, -1)
        
        if h < 0 or h > 23:
            continue
        
        if min_raw == "半":
            minute = 30
        elif min_raw.isdigit():
            minute = int(min_raw)
        elif min_raw in cn_map:
            minute = cn_map[min_raw]
        else:
            minute = 0
        
        if minute < 0 or minute > 59:
            minute = 0
        
        times.append(f"{h:02d}:{minute:02d}")
    
    return times


def _parse_sleep_wakeup_correction(text: str) -> dict:
    """
    解析同时包含睡眠和起床时间的校准语句。
    例如："我6点睡17点起"、"应该是6:17睡17:29起"、"昨晚2点睡到早上10点"
    返回: {"sleep": "HH:MM" or None, "wakeup": "HH:MM" or None}
    """
    raw = str(text or "").strip()
    result = {"sleep": None, "wakeup": None}

    times = _extract_all_times(raw)
    if len(times) < 2:
        return result

    sleep_keywords = ["睡", "睡的", "睡觉", "入睡"]
    wakeup_keywords = ["起", "起床", "醒了", "醒来"]

    # 策略1：按关键词-时间就近匹配
    # 找到每个关键词在文本中的位置，然后将最近的时间分配给它
    kw_positions = []
    for kw in sleep_keywords:
        idx = 0
        while True:
            pos = raw.find(kw, idx)
            if pos == -1:
                break
            kw_positions.append((pos, "sleep", kw))
            idx = pos + 1
    for kw in wakeup_keywords:
        idx = 0
        while True:
            pos = raw.find(kw, idx)
            if pos == -1:
                break
            kw_positions.append((pos, "wakeup", kw))
            idx = pos + 1

    # 找到每个时间在文本中的位置
    time_positions = []
    for t in times:
        # 尝试多种格式搜索
        for fmt in [t, t.replace(":", "：")]:
            pos = raw.find(fmt)
            if pos != -1:
                time_positions.append((pos, t))
                break

    # 对每个关键词，找最近的时间
    if kw_positions and time_positions:
        sleep_time_candidates = []
        wakeup_time_candidates = []
        for kw_pos, kw_type, kw_text in kw_positions:
            best_time = None
            best_dist = float("inf")
            for tp_pos, tp_val in time_positions:
                # 关键词可以在时间之前或之后，距离取绝对值
                dist = abs(kw_pos - tp_pos)
                if dist < best_dist and dist <= 20:  # 关键词和时间之间最多20个字符
                    best_dist = dist
                    best_time = tp_val
            if best_time:
                if kw_type == "sleep":
                    sleep_time_candidates.append(best_time)
                else:
                    wakeup_time_candidates.append(best_time)

        if sleep_time_candidates:
            result["sleep"] = sleep_time_candidates[0]
        if wakeup_time_candidates:
            result["wakeup"] = wakeup_time_candidates[0]

    if result["sleep"] and result["wakeup"]:
        # 防止同一个时间被分配给两个关键词
        if result["sleep"] == result["wakeup"] and len(times) >= 2:
            # 重新按位置顺序分配
            sorted_times = sorted(time_positions, key=lambda x: x[0])
            for tp_pos, tp_val in sorted_times:
                # 找最近的关键词类型
                best_type = None
                best_dist = float("inf")
                for kw_pos, kw_type, _ in kw_positions:
                    dist = abs(kw_pos - tp_pos)
                    if dist < best_dist:
                        best_dist = dist
                        best_type = kw_type
                if best_type == "sleep" and result["sleep"] == result["wakeup"]:
                    result["sleep"] = tp_val
                elif best_type == "wakeup" and result["sleep"] == result["wakeup"]:
                    result["wakeup"] = tp_val
        return result

    # 策略2："睡到"模式 — "2点睡到10点"
    if len(times) >= 2 and "睡到" in raw:
        result["sleep"] = times[0]
        result["wakeup"] = times[1]
        return result

    # 策略3：基于时间范围推断
    if len(times) >= 2:
        sleep_hour = int(times[0].split(":")[0])
        wakeup_hour = int(times[1].split(":")[0])

        if 0 <= sleep_hour <= 9 and 12 <= wakeup_hour <= 23:
            result["sleep"] = times[0]
            result["wakeup"] = times[1]
        elif 12 <= sleep_hour <= 23 and 0 <= wakeup_hour <= 12:
            result["sleep"] = times[1]
            result["wakeup"] = times[0]
        elif "睡" in raw and "起" in raw:
            sleep_pos = raw.find("睡")
            wake_pos = raw.find("起")
            if sleep_pos < wake_pos:
                result["sleep"] = times[0]
                result["wakeup"] = times[1]
            else:
                result["sleep"] = times[1]
                result["wakeup"] = times[0]

    return result


def apply_fast_correction(text: str, manager: Any) -> bool:
    raw = str(text or "").strip()
    if not raw or manager is None:
        return False
    if not has_correction_intent(raw):
        return False
    changed = False
    corrected_time = extract_time_hhmm(raw)
    corrected_part = ""
    corrected_part_match = re.search(
        r"(?:(?<!不)是|改成|应该是|更新为)\s*([^，。！？\n]{1,24})", raw
    )
    if corrected_part_match:
        corrected_part = str(corrected_part_match.group(1) or "").strip()
        corrected_time_from_part = extract_time_hhmm(corrected_part)
        if corrected_time_from_part:
            corrected_time = corrected_time_from_part

    has_sleep_intent = any(k in raw for k in ["睡了", "睡的", "睡觉", "入睡"])
    has_wakeup_intent = any(k in raw for k in ["起床", "起", "醒了", "刚醒", "早安", "早上好"])
    
    if has_sleep_intent and has_wakeup_intent:
        parsed = _parse_sleep_wakeup_correction(raw)
        if parsed["sleep"]:
            manager.record_sleep(parsed["sleep"])
            changed = True
        if parsed["wakeup"]:
            manager.record_wakeup(
                parsed["wakeup"], source="user_manual", force=True
            )
            changed = True
    elif has_wakeup_intent:
        manager.record_wakeup(
            corrected_time or None, source="user_manual", force=True
        )
        changed = True
    elif has_sleep_intent:
        manager.record_sleep(corrected_time or None)
        changed = True

    if any(k in raw for k in ["早餐", "早饭", "午餐", "午饭", "晚餐", "晚饭"]):
        meal_type = _infer_meal_type(raw)
        meal_text = corrected_part or raw
        if "没吃" in meal_text or "没有吃" in meal_text:
            manager.upsert_meal(meal_type, "未吃")
            changed = True
        elif any(k in meal_text for k in ["吃了", "吃过", "有吃"]):
            manager.upsert_meal(meal_type, _extract_meal_content(meal_text))
            changed = True

    return changed


def _extract_corrected_part(raw: str) -> str:
    corrected_part_match = re.search(
        r"(?:(?<!不)是|改成|应该是|更新为)\s*([^，。！？\n]{1,24})", raw
    )
    if not corrected_part_match:
        return ""
    return str(corrected_part_match.group(1) or "").strip()


def _apply_correction_by_intent(raw: str, manager: Any, intent: str) -> bool:
    normalized_intent = str(intent or "").strip().upper()
    corrected_time = extract_time_hhmm(raw)
    corrected_part = _extract_corrected_part(raw)
    if corrected_part:
        corrected_time_from_part = extract_time_hhmm(corrected_part)
        if corrected_time_from_part:
            corrected_time = corrected_time_from_part

    is_yesterday = bool(re.search(r"(昨晚|昨天|昨夜|昨天晚上)", raw))
    target_date = None
    if is_yesterday:
        from datetime import timedelta
        target_date = (get_current_time() - timedelta(days=1)).strftime("%Y-%m-%d")

    if normalized_intent == "CORRECT_WAKEUP":
        manager.record_wakeup(
            corrected_time or None,
            source="user_manual",
            target_date=target_date,
            force=True,
        )
        _sync_wakeup_to_active_care(corrected_time)
        return True
    if normalized_intent == "CORRECT_SLEEP":
        manager.record_sleep(corrected_time or None, target_date=target_date)
        _sync_sleep_to_active_care(corrected_time, target_date)
        return True
    if normalized_intent == "CORRECT_MEAL":
        meal_type = _infer_meal_type(raw)
        meal_text = corrected_part or raw
        if "没吃" in meal_text or "没有吃" in meal_text:
            manager.upsert_meal(meal_type, "未吃")
            return True
        if any(k in meal_text for k in ["吃了", "吃过", "有吃"]):
            manager.upsert_meal(meal_type, _extract_meal_content(meal_text))
            return True
    return False


async def apply_semantic_correction(text: str, manager: Any) -> bool:
    raw = str(text or "").strip()
    if not raw or manager is None:
        return False
    try:
        from core.services.data_ops.bert_analyzer import get_bert_analyzer

        analyzer = get_bert_analyzer()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            analyzer.analyze_intent,
            raw,
            ["CORRECT_WAKEUP", "CORRECT_SLEEP", "CORRECT_MEAL", "NONE"],
        )
        intent = str((result or {}).get("intent") or "NONE").upper()
        conf = float((result or {}).get("confidence") or 0.0)
        if conf < 0.70:
            return False
        return _apply_correction_by_intent(raw, manager, intent)
    except Exception:
        return False
