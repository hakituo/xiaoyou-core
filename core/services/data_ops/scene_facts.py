"""明确的角色现场纠正提取；主语和地点词由调用方配置。"""

import re


def extract_explicit_scene_facts(text: str, *, names=(), location_terms=()) -> dict:
    """只读提取简单陈述，疑问、否定与过去时不当作当前事实。"""
    if not text or re.search(r"[?？]|(?:吗|么|是不是|是否|以前|昨天|上次|那天|假如|如果|要是|不是|不在|没在)", text):
        return {}
    subject = "(?:" + "|".join(re.escape(n) for n in ("你", *names) if n) + ")"
    result = {}
    if location_terms:
        locations = "|".join(re.escape(s) for s in sorted(location_terms, key=len, reverse=True))
        found = re.search(rf"{subject}(?:现在|刚刚|刚才)?(?:在|到了|回到|去了)\s*([^，。！？?]*?(?:{locations}))", text)
        if found:
            result["location"] = found.group(1).strip()
    found = re.search(rf"{subject}(?:今天|现在)?穿(?:着|的是)?\s*([^，。！？?]{{1,36}})", text)
    if found:
        result["clothing"] = found.group(1).strip()
    return result
