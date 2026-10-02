import re
from typing import Any, Dict


_RETROSPECTIVE_PATTERNS = [
    r"昨天",
    r"昨晚",
    r"前天",
    r"之前",
    r"以前",
    r"那天",
    r"当时",
    r"刚才",
    r" earlier ",
    r" yesterday ",
    r" last night ",
    r" previously ",
]

_FUTURE_PATTERNS = [
    r"待会",
    r"一会",
    r"稍后",
    r"等会",
    r"等下",
    r"明天",
    r"准备",
    r"打算",
    r"要去",
    r"想去",
    r"计划",
    r" later ",
    r" tomorrow ",
    r" going to ",
    r" plan to ",
]

_HYPOTHETICAL_PATTERNS = [
    r"如果",
    r"假如",
    r"要是",
    r"好像",
    r"比如",
    r"假设",
    r" if ",
    r" suppose ",
    r" maybe ",
]

_REPORTED_SPEECH_PATTERNS = [
    r"她说",
    r"他说",
    r"你说",
    r"有人说",
    r"她跟我说",
    r"他跟我说",
    r" she said ",
    r" he said ",
    r" they said ",
]

_INSTRUCTION_PREFIXES = [
    "去",
    "快去",
    "记得",
    "别忘了",
    "你去",
    "你该",
    "你要",
    "该去",
    "要不要",
]

_NEGATION_PATTERNS = [
    r"没",
    r"没有",
    r"不是",
    r"并没有",
    r"还没",
    r" not ",
    r" didn't ",
    r" don't ",
]

_CORRECTION_PATTERNS = [
    r"更正",
    r"记错",
    r"不对",
    r"改成",
    r"不是.*是",
    r"自己编的",
    r"编的",
    r"搞错",
    r"弄错",
    r"写错",
    r"你.{0,4}(记错|搞错|弄错|写错|编|瞎|乱)",
    r" correction ",
    r" actually ",
]

_RECORD_REFERENCE_PATTERNS = [
    r"记录的",
    r"记录也是",
    r"记录里",
    r"写的",
    r"存的",
    r"显示的",
    r"记的",
    r"本地记录",
    r"你记录",
    r"你写的",
    r"你存的",
]

_SELF_MARKERS = [
    "我",
    "我在",
    "我刚",
    "我已经",
    "刚",
    "刚刚",
    "已经",
    "才",
    "i ",
    "i'm",
    "i am",
    "i just",
    "i already",
]


def _contains_any(text: str, patterns: list[str]) -> bool:
    value = f" {str(text or '').strip().lower()} "
    for pattern in patterns:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return True
    return False


def analyze_discourse(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    lowered = raw.lower()
    is_question = ("？" in raw) or ("?" in raw) or bool(
        re.search(r"(?:吗|呢|多久|多少|几点|什么|怎么|为什么)(?:[啊呀吧呢嘛哈，。！\s]*)$", raw)
    )
    is_instruction = any(raw.startswith(prefix) for prefix in _INSTRUCTION_PREFIXES) or (
        "提醒你" in raw
        or "建议你" in raw
        or "你应该" in raw
        or "you should" in lowered
        or "remember to" in lowered
    )
    if is_instruction and re.search(r"^(去|快去)\s*(睡|休息|躺)", raw):
        is_instruction = False
    is_retrospective = _contains_any(raw, _RETROSPECTIVE_PATTERNS)
    is_future_plan = _contains_any(raw, _FUTURE_PATTERNS)
    is_hypothetical = _contains_any(raw, _HYPOTHETICAL_PATTERNS)
    is_reported_speech = _contains_any(raw, _REPORTED_SPEECH_PATTERNS)
    contains_negation = _contains_any(raw, _NEGATION_PATTERNS)
    is_correction = _contains_any(raw, _CORRECTION_PATTERNS)
    is_record_reference = _contains_any(raw, _RECORD_REFERENCE_PATTERNS)
    self_report_like = any(marker in raw for marker in _SELF_MARKERS[:7]) or any(
        marker in lowered for marker in _SELF_MARKERS[7:]
    )

    discourse_label = "GENERIC_CHAT"
    if is_reported_speech:
        discourse_label = "REPORTED_SPEECH"
    elif is_instruction:
        discourse_label = "INSTRUCTION"
    elif is_question:
        discourse_label = "QUESTION"
    elif is_hypothetical:
        discourse_label = "HYPOTHETICAL"
    elif is_future_plan:
        discourse_label = "FUTURE_PLAN"
    elif is_correction:
        discourse_label = "CORRECTION"
    elif is_record_reference:
        discourse_label = "RECORD_REFERENCE"
    elif is_retrospective and self_report_like:
        discourse_label = "RETROSPECTIVE_SELF_REPORT"
    elif self_report_like:
        discourse_label = "CURRENT_SELF_REPORT"

    trigger_blocked = (
        is_instruction
        or is_question
        or is_hypothetical
        or is_reported_speech
        or is_future_plan
        or is_retrospective
        or is_correction
        or is_record_reference
    )

    return {
        "discourse_label": discourse_label,
        "is_question": is_question,
        "is_instruction": is_instruction,
        "is_retrospective": is_retrospective,
        "is_future_plan": is_future_plan,
        "is_hypothetical": is_hypothetical,
        "is_reported_speech": is_reported_speech,
        "contains_negation": contains_negation,
        "is_correction": is_correction,
        "is_record_reference": is_record_reference,
        "self_report_like": self_report_like,
        "trigger_blocked": trigger_blocked,
    }


def infer_state_event(text: str, discourse: Dict[str, Any]) -> str:
    raw = str(text or "").strip()
    lowered = raw.lower()
    if not raw:
        return "NONE"
    if not isinstance(discourse, dict):
        discourse = analyze_discourse(raw)
    if discourse.get("trigger_blocked") or discourse.get("contains_negation"):
        return "NONE"

    # 起床
    if any(token in raw for token in ["醒了", "醒啦", "刚醒", "起床", "起来了", "早安", "早上好", "被吵醒", "被叫醒", "自然醒", "睡醒", "醒来", "睡够了", "睡饱了"]):
        return "WAKEUP_NOW"
    
    # 睡觉
    if any(token in raw for token in ["晚安", "要睡", "先睡", "去睡", "我睡了", "睡觉了", "困了", "躺下", "睡了", "睡觉", "准备睡"]):
        if not any(token in raw for token in ["洗澡", "洗漱", "洗头"]):
            return "SLEEP_NOW"
    
    # 喝水
    if any(token in raw for token in ["喝水", "喝了水", "喝杯水", "喝点水", "补充水分", "喝了杯水", "喝水了"]):
        return "DRINK_NOW"
    
    # 饮食
    if any(token in raw for token in ["吃了", "吃过", "有吃", "吃饭", "正在吃", "刚吃完", "吃好了", "早餐", "早饭", "午饭", "午餐", "晚饭", "晚餐", "夜宵", "吃早餐", "吃午餐", "吃晚餐", "吃过早餐", "吃过午餐", "吃过晚餐"]):
        return "MEAL_NOW"
    
    # 学习
    if any(token in raw for token in ["学了", "学习了", "复习了", "刷了", "背了", "看了书", "做了作业", "写作业", "写代码", "刷题了", "背单词", "学英语"]):
        return "STUDY_NOW"
    
    # 活动
    if any(token in raw for token in ["出门了", "去玩了", "打游戏", "看了电影", "运动了", "健身了", "逛街了", "旅游了", "出门逛逛", "出去走走", "去玩"]):
        return "ACTIVITY_NOW"
    
    # 健康
    if any(token in raw for token in ["头疼", "头痛", "发烧", "咳嗽", "肚子痛", "胃痛", "胃疼", "不舒服", "头晕", "喉咙痛", "感冒了", "流鼻涕", "嗓子疼"]):
        return "HEALTH_NOW"
    
    # 心情
    if any(token in raw for token in ["心情好", "心情不好", "开心", "难过", "焦虑", "紧张", "生气", "沮丧", "烦", "郁闷", "高兴", "快乐", "伤心"]):
        return "MOOD_NOW"

    if any(token in lowered for token in ["i woke up", "good morning"]):
        return "WAKEUP_NOW"
    if any(token in lowered for token in ["going to sleep", "good night", "i'm sleepy"]):
        return "SLEEP_NOW"
    return "NONE"
