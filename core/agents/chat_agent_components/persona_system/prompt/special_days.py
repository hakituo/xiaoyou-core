"""
特殊日子检测模块
负责检测节假日、生日等特殊日子，生成相应的提示注入文本
"""

from datetime import date, timedelta
from typing import List, Dict, Optional

# 记录今天是否已经注入过special days（只注入一次）
_last_injected_date: date = None

# 常规节假日配置（月-日格式）
HOLIDAYS = {
    "01-01": "元旦",
    "02-14": "情人节",
    "03-08": "妇女节",
    "05-01": "劳动节",
    "05-20": "520表白日",
    "06-01": "儿童节",
    "09-10": "教师节",
    "10-01": "国庆节",
    "11-11": "光棍节/购物节",
    "12-24": "平安夜",
    "12-25": "圣诞节",
}

# 农历节日配置：键为 (农历月, 农历日)，值为名称。
# 农历节日对应的公历日期每年都不同，需通过 _lunar_to_solar 动态换算，
# 不能像公历节日那样硬编码 MM-DD，否则年年漂移（例如七夕曾误硬编码为 08-15）。
LUNAR_HOLIDAYS = {
    (7, 7): "七夕节",
    # 如需扩展，可在此添加，如 (8, 15): "中秋节"、(1, 1): "春节"、(5, 5): "端午节" 等
}

# 农历转公历结果缓存，避免同一年重复计算
_lunar_to_solar_cache: Dict[tuple, date] = {}


def _lunar_to_solar(year: int, lunar_month: int, lunar_day: int) -> Optional[date]:
    """
    将农历日期转换为公历日期（带缓存与容错）

    Args:
        year: 公历年份
        lunar_month: 农历月 (1-12)
        lunar_day: 农历日 (1-30)

    Returns:
        对应的公历 date；lunar-python 不可用或换算失败时为 None（优雅降级，不注入该节日）
    """
    cache_key = (year, lunar_month, lunar_day)
    if cache_key in _lunar_to_solar_cache:
        return _lunar_to_solar_cache[cache_key]

    result = None
    try:
        from lunar_python import Lunar
        # Lunar.fromYmd 取农历正月的对应日期（闰月以外的常规月份），七夕(七月初七)每年必存在
        lunar = Lunar.fromYmd(year, lunar_month, lunar_day)
        solar = lunar.getSolar()
        result = date(solar.getYear(), solar.getMonth(), solar.getDay())
    except Exception:
        result = None

    _lunar_to_solar_cache[cache_key] = result
    return result

# 特殊生日配置
# name 仅作为内部标识，实际提示文本由 is_user 字段决定措辞
# is_user=True 表示用户（对方）的生日，is_user=False 表示角色自己的生日
SPECIAL_BIRTHDAYS = {
    "05-12": {"name": "用户生日", "is_user": True, "birth_date": "2008-05-12"},
    "11-04": {"name": "Aveline的生日", "is_user": False, "birth_date": "2025-11-04"},
}


def get_special_days(check_date: date = None) -> List[Dict[str, str]]:
    """
    获取指定日期的所有特殊日子
    
    Args:
        check_date: 要检查的日期，默认为今天
        
    Returns:
        特殊日子列表，每项包含:
        - date: 日期字符串 (MM-DD)
        - name: 特殊日子名称
        - type: 类型 (holiday/birthday)
        - is_user_birthday: 是否是用户生日
    """
    if check_date is None:
        check_date = date.today()
    today_str = check_date.strftime("%m-%d")
    result = []
    
    # 检查节假日
    if today_str in HOLIDAYS:
        result.append({
            "date": today_str,
            "name": HOLIDAYS[today_str],
            "type": "holiday",
            "is_user_birthday": False
        })
    
    # 检查特殊生日
    if today_str in SPECIAL_BIRTHDAYS:
        birthday_info = SPECIAL_BIRTHDAYS[today_str]
        result.append({
            "date": today_str,
            "name": birthday_info["name"],
            "type": "birthday",
            "is_user_birthday": birthday_info["is_user"]
        })
    
    # 检查农历节日（动态换算，年年不同）
    for (lunar_month, lunar_day), name in LUNAR_HOLIDAYS.items():
        solar_date = _lunar_to_solar(check_date.year, lunar_month, lunar_day)
        if solar_date is not None and solar_date == check_date:
            result.append({
                "date": today_str,
                "name": name,
                "type": "holiday",
                "is_user_birthday": False
            })
    
    return result


def get_authoritative_calendar_prompt(
    check_date: date = None,
    days_ahead: int = 7,
) -> str:
    """生成带绝对日期的日历事实锚点。

    该锚点每次构建 Prompt 都可注入，用于纠正历史、日记和记忆中的过期
    相对日期。它只负责事实校验，不要求模型主动聊节日。
    """
    if check_date is None:
        check_date = date.today()

    upcoming = []
    for offset in range(0, max(0, days_ahead) + 1):
        target_date = check_date + timedelta(days=offset)
        for item in get_special_days(target_date):
            if item.get("type") != "holiday":
                continue
            upcoming.append(
                {
                    "name": item["name"],
                    "date": target_date.isoformat(),
                    "days_left": offset,
                }
            )

    lines = [
        "\n【权威日历事实锚点】",
        f"- 当前公历日期：{check_date.isoformat()}",
    ]
    if upcoming:
        for item in upcoming:
            relative = "今天" if item["days_left"] == 0 else f"{item['days_left']}天后"
            lines.append(f"- {item['name']}：{item['date']}（{relative}）")
    else:
        lines.append(f"- 未来{max(0, days_ahead)}天内没有已配置的节日")
    lines.extend(
        [
            "- 这里只用于核对日期事实；没有当前任务或自然话题依据时，不要主动提节日。",
            "- 若历史、日记或记忆中的‘今天/明天/节日’与这里冲突，以本锚点为准，禁止复述错误日期。",
        ]
    )
    return "\n".join(lines) + "\n"


def correct_relative_holiday_claims(text: str, check_date: date = None) -> str:
    """纠正生成文本中与权威日历冲突的“今天/明天是节日”断言。

    该函数只替换明确的相对日期事实，不改变消息主题或 MDP 动作。
    Prompt 约束属于软约束，发送前仍需用确定性日历做最后一道防线。
    """
    import re

    if check_date is None:
        check_date = date.today()
    result = str(text or "")

    holiday_dates = []
    for month_day, name in HOLIDAYS.items():
        month, day = (int(part) for part in month_day.split("-"))
        try:
            holiday_dates.append((date(check_date.year, month, day), name))
        except ValueError:
            continue
    for (lunar_month, lunar_day), name in LUNAR_HOLIDAYS.items():
        solar_date = _lunar_to_solar(check_date.year, lunar_month, lunar_day)
        if solar_date is not None:
            holiday_dates.append((solar_date, name))

    for holiday_date, name in holiday_dates:
        short_name = name.removesuffix("节")
        name_pattern = rf"{re.escape(short_name)}(?:节)?"
        claim_pattern = re.compile(
            rf"(?:今天|明天)\s*(?:是)?\s*{name_pattern}"
            rf"|{name_pattern}\s*(?:是)?\s*(?:今天|明天)"
        )
        days_left = (holiday_date - check_date).days

        def _replace_claim(match: "re.Match[str]") -> str:
            matched_text = match.group(0)
            claimed_days_left = 0 if "今天" in matched_text else 1
            if claimed_days_left == days_left:
                return matched_text
            if days_left == 0:
                return f"今天是{name}"
            if days_left == 1:
                return f"明天是{name}"
            if days_left == 2:
                return f"后天是{name}"
            if days_left > 2:
                return f"还有{days_left}天才到{name}"
            return f"{name}已经过去{abs(days_left)}天"

        result = claim_pattern.sub(_replace_claim, result)

    return result


def remove_invalid_relative_holiday_clauses(
    text: str,
    check_date: date = None,
) -> str:
    """移除包含错误相对节日断言的短句，避免纠正后仍反复聊同一节日。"""
    import re

    if check_date is None:
        check_date = date.today()
    original = str(text or "")
    parts = re.split(r"(?<=[，。！？!?；;—\n])", original)
    kept = []
    for part in parts:
        if correct_relative_holiday_claims(part, check_date) != part:
            continue
        kept.append(part)
    cleaned = "".join(kept)
    cleaned = re.sub(r"^[，。！？!?；;—\s]+", "", cleaned)
    cleaned = re.sub(r"(?<=[，。！？!?；;])—+", "", cleaned)
    cleaned = re.sub(r"[，；;—\s]+(?=\[VOICE\]$)", " ", cleaned)
    return cleaned.strip()


def _get_birthday_age_info(date_str: str) -> str:
    """
    根据 SPECIAL_BIRTHDAYS 中的 birth_date 计算当前年龄

    Args:
        date_str: 月-日格式字符串 (MM-DD)

    Returns:
        年龄字符串，无法计算时返回空字符串
    """
    birthday_info = SPECIAL_BIRTHDAYS.get(date_str, {})
    birth_date_str = birthday_info.get("birth_date", "")
    if not birth_date_str:
        return ""
    try:
        parts = birth_date_str.split("-")
        if len(parts) == 3:
            birth = date(int(parts[0]), int(parts[1]), int(parts[2]))
            today = date.today()
            age = today.year - birth.year
            return str(age)
    except Exception:
        pass
    return ""


def get_special_day_prompt(check_date: date = None) -> str:
    """
    生成特殊日子提示注入文本（当天只注入一次）
    
    Args:
        check_date: 要检查的日期，默认为今天
        
    Returns:
        提示注入文本，如果今天没有特殊日子或已注入过则返回空字符串
    """
    global _last_injected_date
    
    if check_date is None:
        check_date = date.today()
    
    # 今天已经注入过，不再重复注入
    if _last_injected_date == check_date:
        return ""
    
    special_days = get_special_days(check_date)
    
    if not special_days:
        return ""
    
    # 标记今天已注入
    _last_injected_date = check_date
    
    lines = ["\n【今日特殊日子提醒】"]

    for day in special_days:
        if day["type"] == "holiday":
            lines.append(f"- 今天是{day['name']}")
        elif day["type"] == "birthday":
            age_info = _get_birthday_age_info(day.get("date", ""))
            if day["is_user_birthday"]:
                age_suffix = f"，今天{age_info}岁生日！" if age_info else "！"
                lines.append(f"- 🎂 今天是对方的生日{age_suffix}记得送上祝福！")
            else:
                lines.append("- 🎂 今天是你的生日！")

    return "\n".join(lines) + "\n"


def check_upcoming_birthdays(check_date: date = None, days_ahead: int = 7) -> List[Dict[str, str]]:
    """
    检查未来几天是否有生日
    
    Args:
        check_date: 从哪天开始检查，默认为今天
        days_ahead: 提前多少天检查
        
    Returns:
        即将到来的生日列表
    """
    if check_date is None:
        check_date = date.today()
    upcoming = []
    
    for offset in range(1, days_ahead + 1):
        try:
            check_offset_date = check_date + timedelta(days=offset)
        except ValueError:
            continue  # 跨月跨年的问题，简化处理跳过
            
        check_str = check_offset_date.strftime("%m-%d")
        
        if check_str in SPECIAL_BIRTHDAYS:
            birthday_info = SPECIAL_BIRTHDAYS[check_str]
            upcoming.append({
                "date": check_str,
                "name": birthday_info["name"],
                "days_left": offset,
                "is_user": birthday_info["is_user"]
            })
    
    return upcoming


def get_upcoming_birthday_prompt(check_date: date = None, days_ahead: int = 7) -> str:
    """
    生成即将到来的生日提示注入文本（当天只注入一次）
    
    Args:
        check_date: 从哪天开始检查，默认为今天
        days_ahead: 提前多少天检查
        
    Returns:
        提示注入文本，如果已注入过则返回空字符串
    """
    global _last_injected_date
    
    if check_date is None:
        check_date = date.today()
    
    # 今天已经注入过，不再重复注入
    if _last_injected_date == check_date:
        return ""
    
    upcoming = check_upcoming_birthdays(check_date, days_ahead)
    
    if not upcoming:
        return ""
    
    # 标记今天已注入（与get_special_day_prompt共享同一个标记）
    _last_injected_date = check_date
    
    lines = ["\n【即将到来的生日提醒】"]

    for birthday in upcoming:
        if birthday["is_user"]:
            lines.append(f"- 还有{birthday['days_left']}天就是对方的生日，记得提前准备惊喜！")
        else:
            lines.append(f"- 还有{birthday['days_left']}天就是你的生日！")

    return "\n".join(lines) + "\n"
